"""Shadow engine: Agent A enrichment corroboration -> ledger flags for Agent B.

Per the A/B division of labour: Agent A ENRICHES (parses the freeform identifier) and
FLAGS; it does NOT decide truth. This engine runs the DETERMINISTIC corroboration over
A's enriched basis_spread vs the XBRL twin and the spread+SOFR=all-in reconciliation, and
emits per-position FLAGS into the shadow ledger. Agent B then arbitrates the flags against
raw source; the deterministic reconciliation verdict is only a PRIOR to prioritise B's queue.

Rules emitted (rule_name):
- agentA_spread_vs_xbrl : A's parsed spread disagrees with the XBRL basis_spread tag.
  mechanism = reconciliation verdict (agentA|xbrl|both|neither|undeterminable):
    * agentA  -> A likely right, XBRL tag likely wrong  -> status warn (B: confirm + correct)
    * neither -> internally-inconsistent filing          -> status fail (B: investigate)
    * xbrl/both/undeterminable                            -> status warn (low prior)
- agentA_maturity_vs_xbrl, agentA_reference_uncorroborated, agentA_subtotal_candidate:
  see _enrichment_flags.

Check repair REQ-APZ-1 (owner ruling DC-shared-83c62c0bdb, 2026-11-13). The identifier A parses
is the filer's hidden member label, which can be stale; the build publishes what the schedule
prints. So a label-vs-tag disagreement (the trigger above, unchanged) becomes a FLAG only after
the published row is compared with its own printed line:
  1. The printed line is the inline-XBRL table row that carries the row's own fair-value fact
     (pipeline.bdc_xbrl_html_bridge.propose_field_bridges_from_ixbrl, the build's page reader,
     anchored on the fact's contextRef). The flag is dropped only when the rule's own field is
     readable on that line and equal to the published value, and no other field the reader can
     compare (maturity, reference rate, margin, instrument type) differs from it. The subtotal
     rule's flag on a published row is dropped when that line is a position line, not 'Total ...'.
  2. Fail closed: no printed line (no cached page, member printed on several lines, no fair-value
     fact), the rule's field not printed there, or a field the reader could not confirm
     ('validation_needed') -> the flag stays (printed_check says why).
  3. A context that is not a published row (zero-value undrawn line, subtotal, header, JV
     look-through schedule) raises no row flag. One carrying a fair value or cost is written to
     agent_a_unpublished_coverage.csv (informational coverage output; not a ledger rule).
  4. The shadow runner (scripts/shadow_validation_runner.py) runs this engine before it reads
     the flags, so every batch / quarter pass / fund build recomputes them.
  5. The identifier is stored whole (was cut at 300 characters) together with the published
     row_id, accession and context, so a flag joins to its row.
The ``mechanism`` strings are unchanged: the review id hashes the mechanism.

Code review 2026-11-13 (D1-D7): a fund whose grammar fails the held-out gate (or whose gate errors)
keeps its previous flags (carried from agent_a_flags.prev.csv, printed_check 'cohort_excluded') and is
listed in agent_a_cohort_excluded.csv with a WARNING; outputs are sorted and the candidate queries
ordered, so identical inputs give byte-identical files (the adapter's mode(mechanism) breaks ties by
first occurrence); the reference rule keeps its flag when the published spread is blank and the line
prints a cash margin ('spread_missing'); every flag and audit row records line_match ('context',
'member', 'member_ambiguous'), and a member-name match counts only when the member has one context.

Writes <output>/shadow/agent_a_flags.csv, <output>/shadow/agent_a_unpublished_coverage.csv and
<output>/shadow/agent_a_candidates_audit.csv (every candidate's outcome, dropped ones included).

Cohort (DERIVED, not hardcoded): every committed per-CIK grammar that declares a
flattened rate-bearing dominant signature AND passes the A3 held-out (cross-quarter)
gate. This auto-tracks newly promoted grammars and keeps the corroboration scoped to
grammars trustworthy enough that an A-vs-XBRL disagreement is signal, not parser noise.
A grammar that does not generalize across quarters is EXCLUDED (its flags would be noise
for Agent B); a non-rate / non-flattened grammar is SKIPPED. Both are logged, never silent.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import config  # noqa: E402
from pipeline.identifier_held_out import held_out_report  # noqa: E402
from pipeline.identifier_overlay import stage_overlay  # noqa: E402
from pipeline.identifier_rate import GRAMMAR_DIR, apply_grammar, load_grammar  # noqa: E402
from pipeline.identifier_signature import is_aggregate_candidate, load_anchors  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("shadow_agent_a_engine")

# The original hand-verified four (kept as a documented regression anchor; the live
# cohort is derived by build_cohort() below and is a superset of these when they still
# pass the held-out gate against the current cache).
SEED_TARGETS = [
    ("0001993402", "AFFIL SECDEBT ASSETTYPE REFRATE RATE MAT"),
    ("0001278752", "SECDEBT REFRATE RATE MAT"),
    ("0001655050", "AFFIL SECLOAN REFRATE RATE MAT"),
    ("0001633336", "DEBT INVTYPE REFRATE RATE MAT"),
]

FLAGS_NAME = "agent_a_flags.csv"
COVERAGE_NAME = "agent_a_unpublished_coverage.csv"
AUDIT_NAME = "agent_a_candidates_audit.csv"
EXCLUDED_NAME = "agent_a_cohort_excluded.csv"
PREVIOUS_NAME = "agent_a_flags.prev.csv"
OUT = config.OUTPUT_DIR / "shadow" / FLAGS_NAME


def candidate_grammars(grammar_dir=None):
    """Committed grammars that declare a flattened, rate-bearing dominant signature.

    Reads the JSON directly (not load_grammar, so a test can point at a temp dir).
    Returns (candidates, skipped); each is a list of (cik, signature, reason)."""
    grammar_dir = grammar_dir or GRAMMAR_DIR
    candidates, skipped = [], []
    for path in sorted(grammar_dir.glob("*.json")):
        cik = path.stem
        try:
            with open(path, "r", encoding="utf-8") as f:
                g = json.load(f)
        except (OSError, ValueError) as e:
            skipped.append((cik, "", f"unreadable: {e}"))
            continue
        ap = g.get("applies_to", {})
        sig, regime = ap.get("signature"), ap.get("regime")
        if not sig:
            skipped.append((cik, "", "no declared signature (not a rate grammar)"))
        elif regime != "flattened":
            skipped.append((cik, sig, f"regime={regime!r} (not flattened)"))
        else:
            candidates.append((cik, sig, ""))
    return candidates, skipped


def build_cohort(parquet, gate=held_out_report, grammar_dir=None):
    """Derive the held-out-PASS cohort over all committed rate grammars.

    Returns (cohort, excluded, skipped):
      cohort   = [(cik, signature, confidence)]  -- held-out PASS (confidence high|narrow)
      excluded = [(cik, signature, reason)]      -- candidate but held-out FAIL / gate error
      skipped  = [(cik, signature, reason)]      -- not a flattened rate grammar
    """
    candidates, skipped = candidate_grammars(grammar_dir)
    cohort, excluded = [], []
    for cik, sig, _ in candidates:
        try:
            v = gate(cik, sig, parquet)
        except Exception as e:  # one bad grammar must not abort the whole cohort
            excluded.append((cik, sig, f"gate error: {e}"))
            continue
        if v.verdict == "PASS":
            cohort.append((cik, sig, v.confidence))
        else:
            excluded.append((cik, sig, "; ".join(v.reasons[:1]) or "held-out FAIL"))
    return cohort, excluded, skipped

# reconciliation verdict -> ledger status (the disagreement is the flag; verdict is the prior)
_STATUS = {"agentA": "warn", "neither": "fail", "xbrl": "warn",
           "both": "warn", "undeterminable": "warn"}

_FIELDS = ["engine", "rule_name", "tier", "enforcement", "cik", "report_date", "status",
           "metric", "metric_name", "mechanism", "agentA_value_pct", "xbrl_residual",
           "a_residual", "identifier", "row_id", "accession_number", "src_context_id",
           "printed_check", "mismatch_fields", "printed_row", "line_match"]
_SORT_KEY = ("cik", "report_date", "rule_name", "identifier", "row_id", "mechanism", "printed_check")

_COVERAGE_FIELDS = ["cik", "report_date", "rule_name", "identifier", "accession_number",
                    "src_context_id", "fair_value", "cost", "reason"]
_EXCLUDED_FIELDS = ["cik", "signature", "reason", "carried_flags", "previous_file"]

# The field each rule tests. The subtotal rule tests no value: its flag on a published row is
# dropped when the row's own line is a position line (compare_row).
PRIMARY_FIELD = {"agentA_maturity_vs_xbrl": "maturity_date",
                 "agentA_spread_vs_xbrl": "basis_spread",
                 "agentA_reference_uncorroborated": "reference_rate_type"}
SUBTOTAL_RULE = "agentA_subtotal_candidate"
_SPREAD_TOL = 0.005  # percentage points
_MONEY_FLOOR = 1.0   # dollars: an unpublished context below this carries nothing


def _flag(rule_name, cik, rd, status, mechanism, ident, *, metric="", metric_name="",
          a_val="", xresid="", aresid="", tier="tight"):
    # identifier kept whole (REQ-APZ-1 condition 5: the 300-character cut broke the join to the row)
    return {"engine": "agentA", "rule_name": rule_name, "tier": tier,
            "enforcement": "advisory", "cik": cik, "report_date": str(rd)[:10], "status": status,
            "metric": metric, "metric_name": metric_name, "mechanism": mechanism,
            "agentA_value_pct": a_val, "xbrl_residual": xresid, "a_residual": aresid,
            "identifier": str(ident), "row_id": "", "accession_number": "", "src_context_id": "",
            "printed_check": "", "mismatch_fields": "", "printed_row": "", "line_match": ""}


def _spread_flags(cik, sig, parquet):
    """Deterministic basis_spread vs XBRL + SOFR reconciliation (verdict = B's prior)."""
    out = []
    # every conflict, not the overlay report's first 500: a cap would drop candidates (and clear their
    # findings) depending on scan order (seen on 0001784700, 2026-11-13)
    for c in stage_overlay(cik, sig, parquet, max_conflicts=None).conflict_rows:
        if c["field"] != "basis_spread" or "reconcile_verdict" not in c:
            continue
        v = c["reconcile_verdict"]
        out.append(_flag("agentA_spread_vs_xbrl", cik, c["report_date"], _STATUS.get(v, "warn"),
                         f"reconcile_{v}", c["identifier"], metric=c.get("xbrl_residual", ""),
                         metric_name="xbrl_reconcile_residual_pp", a_val=c["agentA_value"],
                         xresid=c.get("xbrl_residual", ""), aresid=c.get("a_residual", "")))
    return out


def _enrichment_flags(cik, parquet):
    """A's enrich-and-flag outputs over ALL the filer's current-period rows:
      - agentA_subtotal_candidate : a leaked category-subtotal A spotted while parsing.
      - agentA_reference_uncorroborated : A assigned a reference rate but no structured
        basis_spread exists to confirm the loan is floating (Tier-3: possible fixed-loan
        mis-assignment -> B confirms against source).
      - agentA_maturity_vs_xbrl : the identifier-stated maturity != the structured twin
        maturity. The disagreement is the FLAG (descriptor can be stale after an amendment;
        the twin can be a sibling/period mis-tag). B adjudicates which is authoritative per row
        (longitudinal/source evidence); it is NOT decided here and no longer fails A's gate.
    These are candidates; resolve() keeps those the printed line does not answer."""
    import duckdb

    anchors, grammar = load_anchors(cik), load_grammar(cik)
    con = duckdb.connect()
    rows = con.execute(
        f"""SELECT DISTINCT CAST(investment_identifier AS VARCHAR) ident, CAST(report_date AS VARCHAR)[:10] rd,
                   CAST(reference_rate_type AS VARCHAR) xref, TRY_CAST(basis_spread AS DOUBLE) xspread,
                   CAST(maturity_date AS VARCHAR) xmat
            FROM '{parquet}' WHERE CAST(cik AS VARCHAR)='{cik}'
              AND investment_identifier IS NOT NULL
              AND CAST(period AS VARCHAR)=CAST(report_date AS VARCHAR)
            ORDER BY ALL"""
    ).fetchall()
    con.close()

    out = []
    for ident, rd, xref, xspread, xmat in rows:
        if is_aggregate_candidate(ident, anchors):
            out.append(_flag(SUBTOTAL_RULE, cik, rd, "warn",
                             "category_keyword_no_position", ident))
            continue  # subtotals are not positions -> skip the rate checks
        parsed = apply_grammar(ident, grammar)
        a_ref = parsed.get("reference_rate_type")
        xref_blank = not xref or str(xref).strip().lower() in ("", "none", "nan")
        if a_ref and xref_blank and (xspread is None or xspread == 0):
            out.append(_flag("agentA_reference_uncorroborated", cik, rd, "warn",
                             f"ref_{a_ref}_no_structured_spread", ident, a_val=a_ref))
        a_mat = parsed.get("maturity_date")
        x_mat = str(xmat)[:10] if xmat and str(xmat).strip().lower() not in ("", "none", "nan") else None
        if a_mat and x_mat and a_mat != x_mat:
            out.append(_flag("agentA_maturity_vs_xbrl", cik, rd, "warn",
                             "identifier_maturity_ne_structured", ident,
                             metric_name="parsed_vs_twin_date", a_val=a_mat, xresid=x_mat))
    # one candidate per (rule, quarter, identifier): the DISTINCT above can still repeat an
    # identifier whose contexts carry different structured values
    seen, uniq = set(), []
    for f in out:
        key = (f["rule_name"], f["report_date"], f["identifier"])
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


# ---------------------------------------------------------------------------------------------
# Printed-line comparison (REQ-APZ-1)
# ---------------------------------------------------------------------------------------------

def _norm_ident(value: Any) -> str:
    return " ".join(str(value or "").replace(" ", " ").split()).lower()


def _blank(value: Any) -> bool:
    return value is None or str(value).strip().lower() in ("", "none", "nan", "nat", "<na>")


def _num(value: Any) -> float | None:
    if _blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_INSTRUMENT_CLASSES = (
    ("delayed_draw", re.compile(r"(?i)delayed[\s-]*draw|\bddtl?\b")),
    ("revolver", re.compile(r"(?i)\brevolv")),
    ("term_loan", re.compile(r"(?i)\bterm\s+loan")),
    ("bond", re.compile(r"(?i)\bbonds?\b")),
)
_PUBLISHED_CLASS = {"delayed draw term loan": "delayed_draw", "delayed draw": "delayed_draw",
                    "revolver": "revolver", "term loan": "term_loan"}


def printed_instrument_class(printed_row: str) -> str | None:
    """The loan class the printed line names, first match in priority order; None if it names none.

    'Delayed Draw Term Loan' is a delayed draw, not a term loan; a bond is a bond only when the line
    names no loan class."""
    for name, pattern in _INSTRUMENT_CLASSES:
        if pattern.search(printed_row or ""):
            return name
    return None


def _published_class(instrument_type: Any) -> str | None:
    """'none' for an empty instrument_type; None (not comparable) for a class the page cannot name."""
    if _blank(instrument_type):
        return "none"
    return _PUBLISHED_CLASS.get(str(instrument_type).strip().lower())


def printed_values(bridge: dict | None) -> dict[str, Any]:
    """What the row's own printed line says, per field; a field the reader could not read is absent.

    reference_rate_type '' means the line prints no reference rate in a reference-rate column
    (fixed rate); basis_spread None then means no margin is printed."""
    out: dict[str, Any] = {}
    if not bridge:
        return out
    if bridge.get("maturity_status") == "value" and not _blank(bridge.get("maturity_date")):
        out["maturity_date"] = str(bridge["maturity_date"])[:10]
    rstat = bridge.get("reference_rate_status")
    if rstat == "value" and not _blank(bridge.get("reference_rate_type")):
        out["reference_rate_type"] = str(bridge["reference_rate_type"]).strip().upper()
        margin = _num(bridge.get("printed_margin"))
        if margin is not None:
            out["basis_spread"] = margin
    elif rstat == "not_applicable":
        out["reference_rate_type"] = ""
        out["basis_spread"] = None
    cls = printed_instrument_class(bridge.get("printed_row") or "")
    if cls is not None:
        out["instrument_type"] = cls
    return out


def unreadable_fields(bridge: dict | None) -> list[str]:
    """Fields the line prints but the reader could not confirm ('validation_needed': e.g. a benchmark
    code it does not know, SARON or STIBOR on Apollo's Yellow Castle lines). Fail closed on them."""
    if not bridge:
        return []
    out = []
    if bridge.get("maturity_status") == "validation_needed":
        out.append("maturity_date")
    if bridge.get("reference_rate_status") == "validation_needed":
        out.append("reference_rate_type")
    return out


_INVISIBLE = str.maketrans({"​": " ", " ": " ", "﻿": " "})
# 'CODE + n' / 'CODE n' margin on a line; group 3 is the text right after the number
_FLOAT_MARGIN_RE = re.compile(
    r"\b(SOFR|SF|S|LIBOR|L|EURIBOR|E|PRIME|P|SONIA|SARON|STIBOR|CORRA|BBSY|BBSW|CDOR|C|NIBOR|SN|SA)"
    r"(?:\s*\([A-Z0-9]{1,3}\))?\s*(\+|(?<=[A-Z]{4})\s)\s*(\d{1,4}(?:\.\d+)?)\s*%?([^|;,)]{0,12})")


def first_cell(printed_row: str) -> str:
    """The first non-blank cell of a printed row (zero-width and no-break spaces count as blank)."""
    for cell in str(printed_row or "").split("|"):
        text = cell.translate(_INVISIBLE).strip()
        if text:
            return text
    return ""


def is_total_line(printed_row: str) -> bool:
    from pipeline.bdc_xbrl_html_bridge import _SUBTOTAL_RE
    return bool(_SUBTOTAL_RE.search(first_cell(printed_row)))


def printed_floating_margin(bridge: dict) -> float | None:
    """A non-zero cash margin the line prints over a benchmark (the reader's printed_margin, else the
    first 'CODE + n' on the line that is not marked PIK); None if the line prints none."""
    m = _num(bridge.get("printed_margin"))
    if m:
        return m
    for _code, _sep, num, tail in _FLOAT_MARGIN_RE.findall(str(bridge.get("printed_row") or "")):
        value = float(num)
        if "." not in num and value >= 25:
            value /= 100.0  # basis points
        if value > 0 and "PIK" not in tail.upper():
            return value
    return None


def field_differs(field: str, published: Any, printed: Any) -> bool:
    """True when the published value differs from the printed one (both read, so comparable)."""
    if field == "maturity_date":
        return _blank(published) or str(published)[:10] != printed
    if field == "reference_rate_type":
        return ("" if _blank(published) else str(published).strip().upper()) != printed
    if field == "basis_spread":
        pub = _num(published)
        if printed is None:  # fixed rate: no margin printed
            return pub not in (None, 0.0)
        return pub is None or abs(pub - float(printed)) > _SPREAD_TOL
    if field == "instrument_type":
        pub = _published_class(published)
        if pub is None:
            return False  # a published class the page vocabulary cannot name (Unitranche)
        if printed == "bond":
            return pub != "none"  # the taxonomy has no bond class: a bond publishes no loan class
        return pub != printed
    raise ValueError(field)


def compare_row(rule_name: str, published: dict, bridge: dict | None) -> tuple[str, list[str]]:
    """(printed_check, mismatched fields) of one published row against its own printed line.

    printed_check: 'equal' (flag dropped), 'mismatch', 'spread_missing', 'line_not_found',
    'field_unreadable', 'field_not_printed', 'subtotal_line'. Everything but 'equal' keeps the flag
    (fail closed).

    The subtotal rule tests no value: a published row whose own printed line is a position line
    (first non-blank cell not a total) is a position, and the flag is dropped.
    The reference rule fires on 'reference but no structured spread': it stays when the published
    spread is blank or zero and the line prints a non-zero cash margin (review D3, orchestrator
    decision 2026-11-13)."""
    if not bridge or _blank(bridge.get("printed_row")):
        return "line_not_found", []
    if rule_name == SUBTOTAL_RULE:
        return ("subtotal_line", []) if is_total_line(bridge["printed_row"]) else ("equal", [])
    printed = printed_values(bridge)
    diffs = [f for f in ("maturity_date", "reference_rate_type", "basis_spread", "instrument_type")
             if f in printed and field_differs(f, published.get(f), printed[f])]
    if diffs:
        return "mismatch", diffs
    if (rule_name == "agentA_reference_uncorroborated" and not _num(published.get("basis_spread"))
            and printed_floating_margin(bridge)):
        return "spread_missing", ["basis_spread"]
    unread = unreadable_fields(bridge)
    if unread:
        return "field_unreadable", unread
    if PRIMARY_FIELD[rule_name] not in printed:
        return "field_not_printed", []
    return "equal", []


class PageReader:
    """The build's page reader, once per filing: {context_ref: bridge} and {member: bridge}."""

    def __init__(self, reader: Callable[..., dict] | None = None):
        if reader is None:
            from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl as reader
        self._reader = reader
        self._cache: dict[tuple[str, str, str], tuple[dict, dict]] = {}
        self.errors: Counter = Counter()

    def clear(self) -> None:
        self._cache.clear()

    def lookup(self, cik: str, accession: str, report_date: str, context: str, ident: str) -> dict | None:
        return self.lookup_with_method(cik, accession, report_date, context, ident)[0]

    def lookup_with_method(self, cik: str, accession: str, report_date: str, context: str,
                           ident: str) -> tuple[dict | None, str]:
        """(bridge, 'context' | 'member' | '') - by the row's own fair-value context first, else by
        member name."""
        key = (cik, accession, report_date)
        if key not in self._cache:
            by_ctx: dict[str, dict] = {}
            by_member: dict[str, dict] = {}
            try:
                res = self._reader(cik=cik, accession_number=accession, report_date=report_date)
            except Exception as e:  # unreadable page -> fail closed for its rows
                self.errors[type(e).__name__] += 1
                res = {"bridges": []}
            for b in res.get("bridges", []):
                ctx = (b.get("match_evidence") or {}).get("context_ref")
                if ctx:
                    by_ctx[ctx] = b
                by_member[_norm_ident(b.get("raw_id_lower"))] = b
            self._cache[key] = (by_ctx, by_member)
        by_ctx, by_member = self._cache[key]
        if context in by_ctx:
            return by_ctx[context], "context"
        b = by_member.get(_norm_ident(ident))
        return (b, "member") if b is not None else (None, "")


def resolve(candidates: list[dict], contexts: list[dict], published: list[dict],
            page: PageReader, audit: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Turn label-vs-tag candidates into flags on published rows, plus coverage rows.

    contexts: current-period extracted rows {identifier, report_date, accession_number,
              src_context_id, fair_value, cost}.
    published: published rows {row_id, identifier, report_date, accession_number, src_context_id,
               maturity_date, basis_spread, reference_rate_type, instrument_type, record_class}.
    audit: if given, receives one row per candidate x published row with its printed_check,
           including dropped ones ('equal') and unpublished candidates ('unpublished').
    """
    def note(cand, check, p=None, bridge=None, diffs=(), method=""):
        if audit is None:
            return
        a = dict(cand)
        a.update({"row_id": (p or {}).get("row_id") or "", "accession_number": (p or {}).get("accession_number") or "",
                  "src_context_id": (p or {}).get("src_context_id") or "", "printed_check": check,
                  "mismatch_fields": ";".join(diffs), "printed_row": ((bridge or {}).get("printed_row") or "")[:400],
                  "line_match": method})
        audit.append(a)

    ctx_by_ident: dict[tuple[str, str], list[dict]] = {}
    for c in contexts:
        ctx_by_ident.setdefault((str(c["report_date"])[:10], _norm_ident(c["identifier"])), []).append(c)
    pub_by_ident: dict[tuple[str, str], list[dict]] = {}
    pub_by_ctx: dict[tuple[str, str, str], list[dict]] = {}
    for p in published:
        rd = str(p["report_date"])[:10]
        if p.get("record_class") == "underlying_schedule":
            continue
        pub_by_ident.setdefault((rd, _norm_ident(p["identifier"])), []).append(p)
        pub_by_ctx.setdefault((rd, str(p.get("accession_number") or ""), str(p.get("src_context_id") or "")),
                              []).append(p)
    jv = {(str(p["report_date"])[:10], _norm_ident(p["identifier"])) for p in published
          if p.get("record_class") == "underlying_schedule"}
    jv_ctx = {(str(p["report_date"])[:10], str(p.get("accession_number") or ""), str(p.get("src_context_id") or ""))
              for p in published if p.get("record_class") == "underlying_schedule"}

    flags: list[dict] = []
    coverage: list[dict] = []
    for cand in candidates:
        key = (cand["report_date"], _norm_ident(cand["identifier"]))
        ctxs = ctx_by_ident.get(key, [])
        rows: dict[str, dict] = {}
        for p in pub_by_ident.get(key, []):
            rows[p["row_id"]] = p
        for c in ctxs:
            for p in pub_by_ctx.get((key[0], str(c.get("accession_number") or ""),
                                     str(c.get("src_context_id") or "")), []):
                rows[p["row_id"]] = p
        if not rows:
            # not a published row: no row finding; money-bearing contexts go to coverage
            for c in ctxs:
                fv, cost = _num(c.get("fair_value")), _num(c.get("cost"))
                if (fv is not None and abs(fv) >= _MONEY_FLOOR) or (cost is not None and abs(cost) >= _MONEY_FLOOR):
                    coverage.append({"cik": cand["cik"], "report_date": key[0], "rule_name": cand["rule_name"],
                                     "identifier": cand["identifier"],
                                     "accession_number": c.get("accession_number") or "",
                                     "src_context_id": c.get("src_context_id") or "",
                                     "fair_value": "" if fv is None else fv, "cost": "" if cost is None else cost,
                                     "reason": "underlying_schedule" if (key in jv or (
                                         key[0], str(c.get("accession_number") or ""),
                                         str(c.get("src_context_id") or "")) in jv_ctx) else "not_published"})
            if not ctxs:
                # the candidate names no extracted context: nothing to compare -> fail closed
                f = dict(cand)
                f["printed_check"] = "no_context"
                flags.append(f)
                note(cand, "no_context")
            else:
                note(cand, "unpublished")
            continue
        for row_id in sorted(rows):
            p = rows[row_id]
            bridge, method = page.lookup_with_method(cand["cik"], str(p.get("accession_number") or ""), key[0],
                                                     str(p.get("src_context_id") or ""), p["identifier"])
            check, diffs = compare_row(cand["rule_name"], p, bridge)
            if check == "equal" and method == "member" and \
                    len(ctx_by_ident.get((key[0], _norm_ident(p["identifier"])), [])) != 1:
                # found by member name only, and the member has several contexts: the line may be a
                # sibling's (review D5) -> fail closed
                check, diffs, method = "line_not_found", [], "member_ambiguous"
            note(cand, check, p, bridge, diffs, method)
            if check == "equal":
                continue
            f = dict(cand)
            f.update({"row_id": row_id, "accession_number": p.get("accession_number") or "",
                      "src_context_id": p.get("src_context_id") or "", "printed_check": check,
                      "mismatch_fields": ";".join(diffs),
                      "printed_row": ((bridge or {}).get("printed_row") or "")[:400], "line_match": method})
            flags.append(f)
    return flags, coverage


def _contexts(con, parquet: str, cik: str) -> list[dict]:
    df = con.execute(f"""SELECT CAST(investment_identifier AS VARCHAR) AS identifier,
            CAST(report_date AS VARCHAR)[:10] AS report_date, CAST(accession_number AS VARCHAR) AS accession_number,
            CAST(src_context_id AS VARCHAR) AS src_context_id, TRY_CAST(fair_value AS DOUBLE) AS fair_value,
            TRY_CAST(cost AS DOUBLE) AS cost
        FROM read_parquet('{parquet}') WHERE CAST(cik AS VARCHAR)='{cik}' AND investment_identifier IS NOT NULL
          AND CAST(period AS VARCHAR)=CAST(report_date AS VARCHAR)
        ORDER BY report_date, identifier, accession_number, src_context_id""").fetchdf()
    return df.to_dict("records")


def _published(con, holdings: str, cik: str) -> list[dict]:
    src = (f"read_parquet('{holdings}')" if holdings.endswith(".parquet")
           else f"read_csv('{holdings}', header=true, all_varchar=true, sample_size=-1)")
    df = con.execute(f"""SELECT CAST(row_id AS VARCHAR) AS row_id, CAST(bdc_investment_identifier AS VARCHAR) AS identifier,
            CAST(report_date AS VARCHAR)[:10] AS report_date, CAST(accession_number AS VARCHAR) AS accession_number,
            CAST(src_context_id AS VARCHAR) AS src_context_id, CAST(maturity_date AS VARCHAR)[:10] AS maturity_date,
            TRY_CAST(basis_spread AS DOUBLE) AS basis_spread, CAST(reference_rate_type AS VARCHAR) AS reference_rate_type,
            CAST(instrument_type AS VARCHAR) AS instrument_type,
            coalesce(CAST(accounting_record_class AS VARCHAR), '') AS record_class
        FROM {src} WHERE lpad(CAST(cik AS VARCHAR), 10, '0')='{cik}' AND CAST(source AS VARCHAR)='bdc'
          AND bdc_investment_identifier IS NOT NULL
        ORDER BY row_id""").fetchdf()
    return df.astype(object).where(df.notna(), None).to_dict("records")


def carry_forward(previous: Path | None, excluded: list[tuple[str, str, str]]) -> tuple[list[dict], list[dict]]:
    """Flags of funds whose grammar left the held-out cohort (or whose gate errored), carried from the
    previous flags file unchanged except printed_check='cohort_excluded' (review D1): leaving the
    cohort must not clear a fund's findings without notice. Returns (carried flags, one record per
    excluded fund)."""
    prev_rows: list[dict] = []
    if previous is not None and Path(previous).exists():
        with open(previous, newline="", encoding="utf-8-sig") as f:
            prev_rows = list(csv.DictReader(f))
    carried, records = [], []
    for cik, sig, reason in excluded:
        mine = [r for r in prev_rows if str(r.get("cik", "")).zfill(10) == cik]
        for r in mine:
            row = {k: (r.get(k) or "") for k in _FIELDS}
            row["cik"] = cik
            row["printed_check"] = "cohort_excluded"
            carried.append(row)
        records.append({"cik": cik, "signature": sig, "reason": reason, "carried_flags": len(mine),
                        "previous_file": str(previous) if previous else ""})
        logger.warning("  WARNING agentA cohort_excluded %s [%s]: %s -> %d previous flags carried forward%s",
                       cik, sig, reason, len(mine),
                       "" if prev_rows else " (NO previous flags file: its findings are not carried)")
    return carried, records


def _sorted(rows: list[dict], key=_SORT_KEY) -> list[dict]:
    return sorted(rows, key=lambda r: tuple(str(r.get(k) or "") for k in key))


def write_outputs(out_dir: Path, flags: list[dict], coverage: list[dict], audit: list[dict],
                  excluded: list[dict]) -> None:
    """Write the four outputs, each sorted, so identical inputs give byte-identical files (review D2:
    the adapter's mode(mechanism) breaks ties by first occurrence, so row order reaches the review id)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, fields, rows, key in (
            (FLAGS_NAME, _FIELDS, flags, _SORT_KEY),
            (COVERAGE_NAME, _COVERAGE_FIELDS, coverage, ("cik", "report_date", "rule_name", "identifier",
                                                         "accession_number", "src_context_id")),
            (AUDIT_NAME, _FIELDS, audit, _SORT_KEY),
            (EXCLUDED_NAME, _EXCLUDED_FIELDS, excluded, ("cik",))):
        with open(out_dir / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(_sorted(rows, key))


def run(*, bdc_holdings: Path, published: Path, out_dir: Path, ciks: list[str] | None = None,
        page: PageReader | None = None, previous: Path | None = None) -> dict:
    import duckdb

    parquet, holdings = Path(bdc_holdings).as_posix(), Path(published).as_posix()
    cohort, excluded, skipped = build_cohort(parquet)
    logger.info("agentA cohort: %d held-out-PASS grammars (candidates %d, FAIL/error %d, "
                "non-rate skipped %d)", len(cohort), len(cohort) + len(excluded),
                len(excluded), len(skipped))
    narrow = [c for c, _, conf in cohort if conf == "narrow"]
    if narrow:
        logger.info("  NARROW-confidence PASS (thin in-era coverage, %d): %s",
                    len(narrow), ", ".join(narrow))
    if ciks:
        wanted = {str(c).zfill(10) for c in ciks}
        cohort = [c for c in cohort if c[0] in wanted]
        excluded = [c for c in excluded if c[0] in wanted]
    carried, excluded_records = carry_forward(previous, excluded)
    page = page or PageReader()
    con = duckdb.connect()
    rows, coverage, audit, checks = [], [], [], Counter()
    n_candidates = 0
    for cik, sig, _conf in cohort:
        cands = _spread_flags(cik, sig, parquet) + _enrichment_flags(cik, parquet)
        n_candidates += len(cands)
        if not cands:
            continue
        flags, cov = resolve(cands, _contexts(con, parquet, cik), _published(con, holdings, cik), page, audit)
        rows += flags
        coverage += cov
        checks.update(f["printed_check"] for f in flags)
        logger.info("  %s: %d candidates -> %d flags, %d coverage rows", cik, len(cands), len(flags), len(cov))
        page.clear()  # one fund's pages at a time in memory
    con.close()

    rows += carried
    checks.update(f["printed_check"] for f in carried)
    write_outputs(Path(out_dir), rows, coverage, audit, excluded_records)
    by_rule = Counter(r["rule_name"] for r in rows)
    logger.info("agentA engine: %d candidates -> %d flags over %d filers -> %s", n_candidates, len(rows),
                len(cohort), out_dir / FLAGS_NAME)
    logger.info("  by rule: %s", dict(by_rule))
    logger.info("  printed_check: %s; page read errors: %s", dict(checks), dict(page.errors))
    logger.info("  unpublished money-bearing contexts -> %s: %d", out_dir / COVERAGE_NAME, len(coverage))
    return {"candidates": n_candidates, "flags": len(rows), "coverage": len(coverage), "checks": dict(checks)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bdc-holdings", default=str(config.BDC_HOLDINGS_PARQUET_FILE))
    ap.add_argument("--published", default=str(config.UNIFIED_HOLDINGS_PARQUET_FILE
                                               if config.UNIFIED_HOLDINGS_PARQUET_FILE.exists()
                                               else config.UNIFIED_HOLDINGS_FILE))
    ap.add_argument("--out-dir", default=str(config.OUTPUT_DIR / "shadow"))
    ap.add_argument("--ciks", nargs="*", default=None, help="limit to these cohort CIKs (measurement)")
    ap.add_argument("--previous", default=None,
                    help="previous flags file (default <out-dir>/agent_a_flags.prev.csv, where the shadow runner "
                         "moves the last build's file); excluded funds' flags are carried from it")
    a = ap.parse_args(argv)
    previous = Path(a.previous) if a.previous else Path(a.out_dir) / PREVIOUS_NAME
    run(bdc_holdings=Path(a.bdc_holdings), published=Path(a.published), out_dir=Path(a.out_dir), ciks=a.ciks,
        previous=previous)
    return 0


if __name__ == "__main__":
    sys.exit(main())
