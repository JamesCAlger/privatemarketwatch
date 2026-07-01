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

Read-only. Writes data/output/shadow/agent_a_flags.csv.

Cohort (DERIVED, not hardcoded): every committed per-CIK grammar that declares a
flattened rate-bearing dominant signature AND passes the A3 held-out (cross-quarter)
gate. This auto-tracks newly promoted grammars and keeps the corroboration scoped to
grammars trustworthy enough that an A-vs-XBRL disagreement is signal, not parser noise.
A grammar that does not generalize across quarters is EXCLUDED (its flags would be noise
for Agent B); a non-rate / non-flattened grammar is SKIPPED. Both are logged, never silent.
"""

from __future__ import annotations

import csv
import json
import logging
import sys

from pipeline import config
from pipeline.identifier_held_out import held_out_report
from pipeline.identifier_overlay import stage_overlay
from pipeline.identifier_rate import GRAMMAR_DIR, apply_grammar, load_grammar
from pipeline.identifier_signature import is_aggregate_candidate, load_anchors

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

OUT = config.DATA_DIR / "output" / "shadow" / "agent_a_flags.csv"


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
           "a_residual", "identifier"]


def _flag(rule_name, cik, rd, status, mechanism, ident, *, metric="", metric_name="",
          a_val="", xresid="", aresid="", tier="tight"):
    return {"engine": "agentA", "rule_name": rule_name, "tier": tier,
            "enforcement": "advisory", "cik": cik, "report_date": rd, "status": status,
            "metric": metric, "metric_name": metric_name, "mechanism": mechanism,
            "agentA_value_pct": a_val, "xbrl_residual": xresid, "a_residual": aresid,
            "identifier": str(ident)[:300]}


def _spread_flags(cik, sig, parquet):
    """Deterministic basis_spread vs XBRL + SOFR reconciliation (verdict = B's prior)."""
    out = []
    for c in stage_overlay(cik, sig, parquet).conflict_rows:
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
        (longitudinal/source evidence); it is NOT decided here and no longer fails A's gate."""
    import duckdb

    anchors, grammar = load_anchors(cik), load_grammar(cik)
    con = duckdb.connect()
    rows = con.execute(
        f"""SELECT CAST(investment_identifier AS VARCHAR) ident, CAST(report_date AS VARCHAR) rd,
                   CAST(reference_rate_type AS VARCHAR) xref, TRY_CAST(basis_spread AS DOUBLE) xspread,
                   CAST(maturity_date AS VARCHAR) xmat
            FROM '{parquet}' WHERE CAST(cik AS VARCHAR)='{cik}'
              AND investment_identifier IS NOT NULL
              AND CAST(period AS VARCHAR)=CAST(report_date AS VARCHAR)"""
    ).fetchall()
    con.close()

    out = []
    for ident, rd, xref, xspread, xmat in rows:
        if is_aggregate_candidate(ident, anchors):
            out.append(_flag("agentA_subtotal_candidate", cik, rd, "warn",
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
    return out


def main(argv=None) -> int:
    parquet = str(config.OUTPUT_DIR / "bdc_holdings.parquet")
    cohort, excluded, skipped = build_cohort(parquet)
    logger.info("agentA cohort: %d held-out-PASS grammars (candidates %d, FAIL/error %d, "
                "non-rate skipped %d)", len(cohort), len(cohort) + len(excluded),
                len(excluded), len(skipped))
    for cik, sig, reason in excluded:
        logger.info("  EXCLUDED %s [%s]: %s", cik, sig, reason)
    narrow = [c for c, _, conf in cohort if conf == "narrow"]
    if narrow:
        logger.info("  NARROW-confidence PASS (thin in-era coverage, %d): %s",
                    len(narrow), ", ".join(narrow))

    rows = []
    for cik, sig, _conf in cohort:
        rows += _spread_flags(cik, sig, parquet)
        rows += _enrichment_flags(cik, parquet)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    by_rule = Counter(r["rule_name"] for r in rows)
    logger.info("agentA engine: %d flags over %d filers -> %s", len(rows), len(cohort), OUT)
    logger.info("  by rule: %s", dict(by_rule))
    return 0


if __name__ == "__main__":
    sys.exit(main())
