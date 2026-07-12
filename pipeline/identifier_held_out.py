"""Agent A / A3 held-out (cross-quarter) gate.

The pooled gate (pipeline.identifier_rate.evaluate_cik) measures a grammar over all
quarters at once, which can hide a per-quarter regression or a format the filer used in
only one quarter that the (pooled) induction sample missed. This module evaluates each
quarter INDEPENDENTLY and renders a promotion verdict per the spec's A3 Decision 2
("all other quarters; >=2 required; not-overfit = correct BOTH ways").

Two distinct held-out signals:
 - GRAMMAR generalization: per-quarter parse-completeness + gating-invariant pass-rate
   must clear thresholds in EVERY quarter (not just pooled).
 - ANCHOR/vocabulary generalization: a format used in only one quarter that the
   induction sample missed shows up as a none-share SPIKE in that quarter. We gate on
   none-share STABILITY (a quarter exceeding the median by > delta), not absolute level
   -- a uniformly high none-share is sparse data (e.g. MidCap), not a held-out failure.

The grammar/anchor configs are held FIXED here (re-running the induction agent per fold
is a separate, expensive calibration experiment, not a deterministic gate). Cache-only,
read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from pipeline.identifier_rate import apply_grammar, evaluate_invariants, load_grammar
from pipeline.identifier_signature import (
    _ANCHOR_PRESENCE_RE,
    _RATE_RE,
    detect_regime,
    keyword_signature,
    load_anchors,
)


@dataclass
class HeldOutVerdict:
    cik: str
    signature: str
    quarters: list = field(default_factory=list)   # per-quarter metric dicts
    verdict: str = "PASS"
    confidence: str = "high"                        # "high" | "narrow" (thin in-era coverage)
    reasons: list = field(default_factory=list)


def held_out_report(
    cik: str,
    signature: str,
    parquet_path: str,
    grammar: dict | None = None,
    anchors=None,
    gating_invariants=None,
    required=None,
    min_quarters: int = 2,
    min_completeness: float = 90.0,
    min_invariant: float = 85.0,
    none_spike_delta: float = 10.0,
    target_regime: str | None = None,
) -> HeldOutVerdict:
    import duckdb

    grammar = grammar or load_grammar(cik)
    anchors = anchors or load_anchors(cik)
    if required is None:
        required = grammar.get("required_fields", [])
    # era-awareness: a grammar only applies to its own regime. Quarters of a DIFFERENT
    # regime (e.g. an early DELIMITED era where rate/maturity live in structured XBRL, not
    # the string) are a different era the flattened grammar legitimately does not cover ->
    # excluded from the verdict but still reported. Default (None) = grammar's own regime.
    if target_regime is None:
        target_regime = grammar.get("applies_to", {}).get("regime")
    if gating_invariants is None:
        # GATE only on SELF-CONTAINED invariants (sum_identity): they check the parse's
        # internal consistency (e.g. total == cash + PIK) with no reference to the structured
        # twin. The pct_agree/date_agree invariants compare the parsed value to the structured
        # twin -- but twins are an unreliable secondary source (stale descriptors lagging
        # amendments, sibling/period mis-tags). When parsed != twin, ~80% of adjudicable
        # maturity cases are the descriptor being stale, not a grammar defect, and which source
        # is authoritative is Agent B's per-row adjudication, NOT an A promotion blocker. So
        # twin comparisons are tracked as ADVISORY (twin_agreement_pct) and emitted as ledger
        # flags for B -- they no longer fail the gate.
        # See data/output/data_investigation_results.md (twin reliability) + adjudication_architecture/B_and_C.
        gating_invariants = [
            inv["name"] for inv in grammar.get("invariants", [])
            if inv["kind"] == "sum_identity"
        ]
    # advisory only (reported, never gated): parsed-vs-structured-twin agreement
    twin_invariants = [
        inv["name"] for inv in grammar.get("invariants", [])
        if inv["kind"] in ("pct_agree", "date_agree")
    ]

    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT CAST(report_date AS VARCHAR) rd, CAST(investment_identifier AS VARCHAR) ident,
               TRY_CAST(interest_rate AS DOUBLE) ti, TRY_CAST(basis_spread AS DOUBLE) ts,
               TRY_CAST(pik_rate AS DOUBLE) tp, CAST(maturity_date AS VARCHAR) tm
        FROM '{parquet_path}'
        WHERE CAST(cik AS VARCHAR) = '{cik}'
          AND investment_identifier IS NOT NULL
          AND CAST(period AS VARCHAR) = CAST(report_date AS VARCHAR)
        """
    ).fetchall()
    con.close()

    # bucket per quarter
    q: dict = {}
    for rd, ident, ti, ts, tp, tm in rows:
        b = q.setdefault(rd, {"n": 0, "none": 0, "sig": 0, "complete": 0,
                              "inv_pass": 0, "inv_dec": 0, "rate": 0, "anchor": 0,
                              "twin_pass": 0, "twin_dec": 0})
        b["n"] += 1
        if _RATE_RE.search(ident):
            b["rate"] += 1
        if _ANCHOR_PRESENCE_RE.search(ident):
            b["anchor"] += 1
        sig = keyword_signature(ident, anchors)
        if sig == "(none)":
            b["none"] += 1
        if sig != signature:
            continue
        b["sig"] += 1
        parsed = apply_grammar(ident, grammar)
        if all(parsed.get(k) is not None for k in required):
            b["complete"] += 1
        twins = {"interest_rate": ti, "basis_spread": ts, "pik_rate": tp, "maturity_date": tm}
        verd = evaluate_invariants(parsed, twins, grammar)
        for name in gating_invariants:
            v = verd.get(name)
            if v in ("pass", "fail"):
                b["inv_dec"] += 1
                if v == "pass":
                    b["inv_pass"] += 1
        for name in twin_invariants:        # advisory only -- never affects the verdict
            v = verd.get(name)
            if v in ("pass", "fail"):
                b["twin_dec"] += 1
                if v == "pass":
                    b["twin_pass"] += 1

    out = HeldOutVerdict(cik=cik, signature=signature)
    per_q = []
    for rd in sorted(q):
        b = q[rd]
        rate_pct = 100.0 * b["rate"] / b["n"] if b["n"] else 0.0
        anchor_pct = 100.0 * b["anchor"] / b["n"] if b["n"] else 0.0
        regime = detect_regime(rate_pct, anchor_pct)
        # era_match: this quarter belongs to the grammar's regime (deterministic, the SAME
        # detect_regime used to route filers -- not a "skip the failing quarter" escape).
        era_match = target_regime is None or regime == target_regime
        per_q.append({
            "quarter": rd,
            "n_rows": b["n"],
            "none_pct": round(100.0 * b["none"] / b["n"], 1) if b["n"] else 0.0,
            "sig_rows": b["sig"],
            "completeness_pct": round(100.0 * b["complete"] / b["sig"], 1) if b["sig"] else None,
            "invariant_pct": round(100.0 * b["inv_pass"] / b["inv_dec"], 1) if b["inv_dec"] else None,
            "twin_agreement_pct": round(100.0 * b["twin_pass"] / b["twin_dec"], 1) if b["twin_dec"] else None,
            "regime": regime,
            "era_match": era_match,
        })
    out.quarters = per_q

    # ---- verdict (over IN-ERA quarters only) ----
    in_era = [r for r in per_q if r["era_match"]]
    excluded = [r for r in per_q if not r["era_match"]]
    if excluded:
        out.reasons.append(
            f"era-excluded {len(excluded)} quarter(s) of a different regime "
            f"(target='{target_regime}'): {', '.join(r['quarter'] for r in excluded)} "
            f"-- the grammar legitimately does not apply there")

    sig_quarters = [r for r in in_era if r["sig_rows"] > 0]
    if len(sig_quarters) < min_quarters:
        out.verdict = "FAIL"
        out.reasons.append(
            f"unvalidated_cross_quarter: signature present in {len(sig_quarters)} in-era "
            f"quarter(s), need >= {min_quarters} (overfit-by-construction risk)")
        return out

    for r in sig_quarters:
        if r["completeness_pct"] is not None and r["completeness_pct"] < min_completeness:
            out.verdict = "FAIL"
            out.reasons.append(
                f"{r['quarter']}: completeness {r['completeness_pct']}% < {min_completeness}% "
                f"(grammar does not generalize to this quarter)")
        if r["invariant_pct"] is not None and r["invariant_pct"] < min_invariant:
            out.verdict = "FAIL"
            out.reasons.append(
                f"{r['quarter']}: gating-invariant {r['invariant_pct']}% < {min_invariant}%")

    # none-share STABILITY over IN-ERA quarters (a different-era quarter's 100% none must
    # not even enter the median or be spike-checked)
    none_vals = [r["none_pct"] for r in in_era]
    med = median(none_vals) if none_vals else 0.0
    for r in in_era:
        if r["none_pct"] > med + none_spike_delta:
            out.verdict = "FAIL"
            out.reasons.append(
                f"{r['quarter']}: none-share {r['none_pct']}% spikes > median {med:.1f}% + "
                f"{none_spike_delta}% (a format this quarter the induction sample likely missed)")

    # power floor: a PASS validated on few in-era quarters (e.g. a recent flattened era after
    # many delimited ones) is thin evidence -> PASS but flag NARROW (lower confidence, route to
    # human, do not auto-promote). Not a FAIL: the in-era quarters genuinely cleared.
    if out.verdict == "PASS" and (len(sig_quarters) < 4 or len(excluded) > len(sig_quarters)):
        out.confidence = "narrow"
        out.reasons.append(
            f"NARROW confidence: only {len(sig_quarters)} in-era quarter(s) validated "
            f"({len(excluded)} era-excluded) -- promote with human review, not auto")

    if out.verdict == "PASS":
        out.reasons.append(
            f"all {len(sig_quarters)} in-era signature-bearing quarters clear completeness "
            f">= {min_completeness}% and invariant >= {min_invariant}%; none-share stable "
            f"(median {med:.1f}%)")
    return out


def print_held_out(v: HeldOutVerdict, log=print):
    log(f"=== A3 held-out gate -- CIK {v.cik}  (sig: {v.signature}) ===")
    log(" quarter       rows   sig  none%  complete%  invariant%  era")
    for r in v.quarters:
        comp = "  n/a" if r["completeness_pct"] is None else f"{r['completeness_pct']:5.1f}"
        inv = "  n/a" if r["invariant_pct"] is None else f"{r['invariant_pct']:5.1f}"
        era = "" if r.get("era_match", True) else f"  [excl:{r.get('regime','')}]"
        log(f"  {r['quarter']}  {r['n_rows']:>6} {r['sig_rows']:>5}  {r['none_pct']:4.1f}    "
            f"{comp}      {inv}{era}")
    log(f"VERDICT: {v.verdict}" + (f" (confidence: {v.confidence})" if v.verdict == "PASS" else ""))
    for reason in v.reasons:
        log(f"  - {reason}")


def main():  # pragma: no cover
    from pipeline import config
    parquet = str(config.OUTPUT_DIR / "bdc_holdings.parquet")
    targets = [
        ("0001993402", "AFFIL SECDEBT ASSETTYPE REFRATE RATE MAT"),
        ("0001278752", "SECDEBT REFRATE RATE MAT"),
        ("0001655050", "AFFIL SECLOAN REFRATE RATE MAT"),
        ("0001633336", "DEBT INVTYPE REFRATE RATE MAT"),
    ]
    for cik, sig in targets:
        print_held_out(held_out_report(cik, sig, parquet))
        print()


if __name__ == "__main__":  # pragma: no cover
    main()
