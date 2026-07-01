"""Agent A / P1 -- deterministic rate-grammar applier + semantic gate.

Applies a hand-authored (later agent-authored) per-CIK ``rate_grammar`` to the freeform
``investment_identifier`` to extract the within-string RATE STRUCTURE the wrapper strips
and never parses: reference_rate_type, basis_spread, interest_rate_floor,
interest_rate_all_in, the derived cash leg, pik_rate, coupon_type, maturity_date.

It then runs the section-4 SEMANTIC gate (cross-twin agreement, fixed/floating
derivation, completeness) and reports pass-rates. It is read-only on holdings and does
NOT merge into production; it stages a provenance-tagged overlay for review.

Grammar store: data/overrides/identifier_rate_grammars/<cik>.json (sibling to the
wrapper config for P1 isolation; may later fold into the wrapper file per open decision).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pipeline import config

GRAMMAR_DIR = config.DATA_DIR / "overrides" / "identifier_rate_grammars"

_REF_MAP_DEFAULT = {"S": "SOFR", "SF": "SOFR", "L": "LIBOR", "P": "PRIME", "E": "EURIBOR"}

# Zero-width / BOM / non-breaking chars that contaminate cached identifier strings
# (e.g. "Interest Rate﻿ 7.06%") and break \s-based extractors. Filer-independent
# encoding artifact -> normalize globally, not per-CIK.
_ZERO_WIDTH_RE = re.compile("[﻿​‌‍⁠]")


def normalize_identifier_text(s: str) -> str:
    """Strip zero-width/BOM chars and map the non-breaking space to a regular space, so
    \\s-based grammar/anchor regexes match. Shared by apply_grammar and keyword_signature."""
    if not s:
        return s
    return _ZERO_WIDTH_RE.sub("", s).replace(" ", " ")


def load_grammar(cik: str) -> dict:
    path = GRAMMAR_DIR / f"{cik}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# Value coercion
# --------------------------------------------------------------------------- #
def _to_pct(raw: str):
    try:
        return round(float(raw), 4)
    except (TypeError, ValueError):
        return None


def _to_iso(mdy: str):
    """m/d/yyyy or m/d/yy -> ISO 'YYYY-MM-DD'. Returns None on parse failure."""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", mdy.strip())
    if not m:
        return None
    mo, da, yr = (int(g) for g in m.groups())
    if yr < 100:
        yr += 2000
    if not (1 <= mo <= 12 and 1 <= da <= 31):
        return None
    return f"{yr:04d}-{mo:02d}-{da:02d}"


def _to_bps_pct(raw: str):
    """basis-points integer -> percent (e.g. '400' -> 4.00, 'SOFR+550' captured as 550 -> 5.50)."""
    try:
        return round(float(raw) / 100.0, 4)
    except (TypeError, ValueError):
        return None


def _coerce(field_type: str, raw: str, mapping: dict | None):
    if field_type == "pct":
        return _to_pct(raw)
    if field_type == "bps":
        return _to_bps_pct(raw)
    if field_type == "date_mdy":
        return _to_iso(raw)
    if field_type == "ref_code":
        key = (raw or "").strip().upper()
        return (mapping or _REF_MAP_DEFAULT).get(key, key or None)
    return (raw or "").strip() or None


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #
def apply_grammar(identifier: str, grammar: dict) -> dict:
    """Extract + derive structured fields from one identifier string. No twin/holdings
    context here -- pure parse. Returns a dict (missing fields -> None)."""
    out: dict = {}
    text = normalize_identifier_text(identifier or "")
    for ex in grammar.get("extractors", []):
        rx = re.compile(ex["regex"], re.I)
        m = rx.search(text)
        val = None
        if m:
            # A malformed extractor can declare a capture group its regex lacks (e.g. a
            # non-capturing '(?:...)' with "group": 1). m.group() would raise IndexError and
            # abort the whole batch. Treat it as no extraction here; validate_proposal screens
            # this class out at staging so it never reaches production.
            try:
                raw = m.group(ex.get("group", 1))
            except IndexError:
                raw = None
            val = _coerce(ex.get("type", "text"), raw, ex.get("map"))
        # Multiple extractors for one field act as FALLBACKS (coalesce): a later extractor that
        # does NOT match must not clobber a value an earlier one already captured. A later MATCH
        # still wins (overwrite-on-match preserved). Without this, a 2nd interest_rate extractor
        # that misses nulls the 1st's value -> spurious held-out completeness FAIL (Great Elm,
        # SLR). Single-extractor-per-field grammars are unaffected.
        if val is not None or ex["field"] not in out:
            out[ex["field"]] = val

    derivs = grammar.get("derivations", {})
    if not isinstance(derivs, dict):
        derivs = {}   # agents sometimes emit "derivations": [] -- a list has no .get(), would crash
    if derivs.get("coupon_type") == "floating_if_reference_rate_else_fixed":
        out["coupon_type"] = "FLOATING" if out.get("reference_rate_type") else "FIXED"
    # PIK convention -> cash leg / total reconciliation
    conv = grammar.get("pik_convention")
    if derivs.get("interest_rate_cash_leg") == "interest_rate_all_in_minus_pik" or conv == "inclusive":
        # stated rate is ALL-IN incl PIK; cash = all_in - pik
        all_in, pik = out.get("interest_rate_all_in"), out.get("pik_rate")
        out["interest_rate_cash_leg"] = (
            round(all_in - (pik or 0.0), 4) if all_in is not None else None
        )
    elif conv == "additive":
        # stated cash + pik are separate; total = cash + pik
        cash, pik = out.get("interest_rate_cash_leg"), out.get("pik_rate")
        if cash is not None and out.get("interest_rate_total") is None:
            out["interest_rate_total"] = round(cash + (pik or 0.0), 4)
    return out


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
def normalize_rate_pct(v):
    """Normalize a stored rate to PERCENT scale, tolerating MIXED decimal/percent storage.

    BDC basis_spread/interest_rate twins are usually decimals (0.0575), but some filers
    (MidCap, Crescent) tag a minority on percent scale (5.75) -- naive *100 then turns
    5.75 into 575 and fabricates a conflict. Rule: a rate stored as a fraction (abs < 1)
    is decimal -> *100; one already >= 1 is percent -> as-is.

    Edge case: a genuine sub-1% rate stored on percent scale (e.g. a 0.50% spread tagged
    as 0.50) is misread as 0.0050% -> 0.50%. Acceptable: BDC spreads/coupons are ~>=1%;
    such a value is an outlier the reconciliation/gate would flag anyway.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f == 0.0:
        return 0.0
    return round(f * 100.0, 4) if abs(f) < 1.0 else round(f, 4)


def _twin_pct(v):
    return normalize_rate_pct(v)


def evaluate_invariants(parsed: dict, twins: dict, grammar: dict) -> dict:
    """Return {invariant_name: 'pass'|'fail'|'na'} for one row.

    Defensive against agent-authored invariants that omit the keys their `kind` requires
    (e.g. a `pct_agree` invariant with no `parsed`): a malformed invariant resolves to 'na'
    instead of raising KeyError and aborting the whole screen/gate over the full population.
    validate_proposal screens this shape out at staging.
    """
    res = {}
    for inv in grammar.get("invariants", []):
        name, kind = inv.get("name"), inv.get("kind")
        if not name:
            continue  # unnamed invariant -- nothing to key the result on
        pk, tk = inv.get("parsed"), inv.get("twin")
        if kind == "pct_agree":
            p = parsed.get(pk) if pk else None
            t = _twin_pct(twins.get(tk)) if tk else None
            if p is None or t is None:
                res[name] = "na"
            else:
                res[name] = "pass" if abs(p - t) <= inv.get("tol", 0.05) else "fail"
        elif kind == "date_agree":
            p = parsed.get(pk) if pk else None
            t = twins.get(tk) if tk else None
            t = str(t)[:10] if t is not None else None
            if p is None or not t:
                res[name] = "na"
            else:
                res[name] = "pass" if p == t else "fail"
        elif kind == "implication":
            ip, tp = inv.get("if_present"), inv.get("then_present")
            if not ip or not tp or parsed.get(ip) is None:
                res[name] = "na"
            else:
                res[name] = "pass" if parsed.get(tp) is not None else "fail"
        elif kind == "sum_identity":
            # total == sum(parts), self-contained (no twin). The strong gate when twins
            # are unreliable (e.g. MidCap mis-binned interest_rate/basis_spread).
            tot_k, parts_k = inv.get("total"), inv.get("parts") or []
            total = parsed.get(tot_k) if tot_k else None
            parts = [parsed.get(p) for p in parts_k]
            if total is None or not parts_k or any(p is None for p in parts):
                res[name] = "na"
            else:
                res[name] = "pass" if abs(total - sum(parts)) <= inv.get("tol", 0.05) else "fail"
        else:
            res[name] = "na"
    return res


# --------------------------------------------------------------------------- #
# Evaluation harness over a CIK
# --------------------------------------------------------------------------- #
_FIELDS = [
    "instrument_type", "reference_rate_type", "basis_spread", "interest_rate_floor",
    "interest_rate_all_in", "interest_rate_total", "interest_rate_cash_leg", "pik_rate",
    "coupon_type", "maturity_date",
]


@dataclass
class GateReport:
    cik: str
    n_signature_rows: int = 0
    n_parsed_complete: int = 0          # all required fields extracted
    fv_in: float = 0.0
    fv_out: float = 0.0
    invariant_pass: dict = field(default_factory=dict)
    invariant_fail: dict = field(default_factory=dict)
    invariant_na: dict = field(default_factory=dict)
    overlay_rows: list = field(default_factory=list)


def evaluate_cik(cik: str, parquet_path: str, signature: str, log=print,
                 required=None) -> GateReport:
    import duckdb

    from pipeline.identifier_signature import keyword_signature, load_anchors

    grammar = load_grammar(cik)
    anchors = load_anchors(cik)
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT CAST(investment_identifier AS VARCHAR) ident,
               CAST(report_date AS VARCHAR) report_date,
               TRY_CAST(fair_value AS DOUBLE) fv,
               TRY_CAST(interest_rate AS DOUBLE) tw_int,
               TRY_CAST(basis_spread AS DOUBLE) tw_spread,
               TRY_CAST(pik_rate AS DOUBLE) tw_pik,
               CAST(maturity_date AS VARCHAR) tw_mat
        FROM '{parquet_path}'
        WHERE CAST(cik AS VARCHAR) = '{cik}'
          AND investment_identifier IS NOT NULL
          AND CAST(period AS VARCHAR) = CAST(report_date AS VARCHAR)
        """
    ).fetchall()
    con.close()

    rep = GateReport(cik=cik)
    if required is None:
        required = grammar.get(
            "required_fields",
            ["interest_rate_all_in", "basis_spread", "reference_rate_type", "maturity_date"],
        )
    for inv in grammar.get("invariants", []):
        rep.invariant_pass[inv["name"]] = 0
        rep.invariant_fail[inv["name"]] = 0
        rep.invariant_na[inv["name"]] = 0

    for ident, report_date, fv, tw_int, tw_spread, tw_pik, tw_mat in rows:
        if keyword_signature(ident, anchors) != signature:
            continue
        rep.n_signature_rows += 1
        rep.fv_in += fv or 0.0
        rep.fv_out += fv or 0.0  # parse never touches FV; preserved by construction

        parsed = apply_grammar(ident, grammar)
        if all(parsed.get(k) is not None for k in required):
            rep.n_parsed_complete += 1

        twins = {"interest_rate": tw_int, "basis_spread": tw_spread,
                 "pik_rate": tw_pik, "maturity_date": tw_mat}
        verd = evaluate_invariants(parsed, twins, grammar)
        for name, v in verd.items():
            {"pass": rep.invariant_pass, "fail": rep.invariant_fail,
             "na": rep.invariant_na}[v][name] += 1

        row = {"cik": cik, "report_date": report_date, "source": "agentA_parse",
               "investment_identifier": ident[:200]}
        row.update({f: parsed.get(f) for f in _FIELDS})
        row.update({f"inv_{k}": v for k, v in verd.items()})
        rep.overlay_rows.append(row)

    return rep


def print_gate(rep: GateReport, log=print):
    n = rep.n_signature_rows
    log(f"=== Agent A P1 gate -- CIK {rep.cik} ===")
    log(f"signature rows: {n:,}")
    if n == 0:
        return
    log(f"parse-completeness (all required fields): {rep.n_parsed_complete:,} "
        f"({100.0*rep.n_parsed_complete/n:.1f}%)")
    log(f"FV preserved: in={rep.fv_in:,.0f}  out={rep.fv_out:,.0f}  "
        f"delta={rep.fv_out-rep.fv_in:,.2f}")
    log("invariant pass-rates (of DECIDED = pass+fail; na excluded):")
    for name in rep.invariant_pass:
        p, fl, na = rep.invariant_pass[name], rep.invariant_fail[name], rep.invariant_na[name]
        decided = p + fl
        rate = f"{100.0*p/decided:.1f}%" if decided else "n/a"
        log(f"  {name:24s} pass={p:>5} fail={fl:>4} na={na:>5}  -> {rate} of decided")


def main():  # pragma: no cover - thin IO wrapper
    import csv

    cik = "0001993402"
    signature = "AFFIL SECDEBT ASSETTYPE REFRATE RATE MAT"
    parquet = str(config.OUTPUT_DIR / "bdc_holdings.parquet")
    rep = evaluate_cik(cik, parquet, signature)
    print_gate(rep)

    out_dir = config.OUTPUT_DIR / "agent_a"
    out_dir.mkdir(exist_ok=True)
    overlay = out_dir / f"identifier_rate_overlay_{cik}.csv"
    if rep.overlay_rows:
        with open(overlay, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rep.overlay_rows[0].keys()))
            w.writeheader()
            w.writerows(rep.overlay_rows)
        print(f"Staged provenance-tagged overlay -> {overlay} ({len(rep.overlay_rows)} rows)")


if __name__ == "__main__":  # pragma: no cover
    main()
