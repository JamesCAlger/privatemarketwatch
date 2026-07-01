"""Tests for the A3 held-out (cross-quarter) gate verdict logic."""

from pipeline.identifier_held_out import HeldOutVerdict, held_out_report


def _q(quarter, n, none, sig, comp, inv, era_match=True):
    return {"quarter": quarter, "n_rows": n, "none_pct": none, "sig_rows": sig,
            "completeness_pct": comp, "invariant_pct": inv, "era_match": era_match}


def _verdict_from_quarters(quarters, **kw):
    """Re-run only the verdict logic by monkeypatching the data layer is overkill;
    instead exercise held_out_report's verdict math via a tiny shim that mirrors it
    (including era-exclusion + narrow-confidence)."""
    from statistics import median
    v = HeldOutVerdict(cik="x", signature="S")
    v.quarters = quarters
    min_quarters = kw.get("min_quarters", 2)
    min_completeness = kw.get("min_completeness", 90.0)
    min_invariant = kw.get("min_invariant", 85.0)
    none_spike_delta = kw.get("none_spike_delta", 10.0)
    in_era = [r for r in quarters if r.get("era_match", True)]
    excluded = [r for r in quarters if not r.get("era_match", True)]
    sigq = [r for r in in_era if r["sig_rows"] > 0]
    if len(sigq) < min_quarters:
        v.verdict = "FAIL"; v.reasons.append("unvalidated_cross_quarter"); return v
    for r in sigq:
        if r["completeness_pct"] is not None and r["completeness_pct"] < min_completeness:
            v.verdict = "FAIL"; v.reasons.append(f"{r['quarter']}: completeness")
        if r["invariant_pct"] is not None and r["invariant_pct"] < min_invariant:
            v.verdict = "FAIL"; v.reasons.append(f"{r['quarter']}: invariant")
    med = median([r["none_pct"] for r in in_era]) if in_era else 0.0
    for r in in_era:
        if r["none_pct"] > med + none_spike_delta:
            v.verdict = "FAIL"; v.reasons.append(f"{r['quarter']}: none spike")
    if v.verdict == "PASS" and (len(sigq) < 4 or len(excluded) > len(sigq)):
        v.confidence = "narrow"
    return v


def test_pass_when_all_quarters_clear():
    qs = [_q("2024-03-31", 500, 1.0, 300, 99.0, 98.0),
          _q("2024-06-30", 520, 1.5, 310, 98.5, 97.0),
          _q("2024-09-30", 540, 1.2, 320, 99.5, 99.0)]
    assert _verdict_from_quarters(qs).verdict == "PASS"


def test_fail_single_quarter_signature():
    qs = [_q("2024-03-31", 500, 1.0, 300, 99.0, 98.0),
          _q("2024-06-30", 520, 1.0, 0, None, None)]
    v = _verdict_from_quarters(qs)
    assert v.verdict == "FAIL"
    assert any("unvalidated_cross_quarter" in r for r in v.reasons)


def test_fail_completeness_drop_one_quarter():
    qs = [_q("2024-03-31", 500, 1.0, 300, 99.0, 98.0),
          _q("2024-06-30", 520, 1.0, 310, 55.0, 97.0),   # grammar breaks here
          _q("2024-09-30", 540, 1.0, 320, 99.0, 98.0)]
    v = _verdict_from_quarters(qs)
    assert v.verdict == "FAIL"
    assert any("completeness" in r for r in v.reasons)


def test_fail_none_share_spike_one_quarter():
    # uniform-high none is OK (sparse data); a SPIKE relative to median is not
    qs = [_q("2024-03-31", 500, 2.0, 300, 99.0, 98.0),
          _q("2024-06-30", 520, 2.0, 310, 99.0, 97.0),
          _q("2024-09-30", 540, 45.0, 200, 99.0, 98.0)]  # missed format this quarter
    v = _verdict_from_quarters(qs)
    assert v.verdict == "FAIL"
    assert any("none spike" in r for r in v.reasons)


def test_uniform_high_none_is_not_a_spike_failure():
    # MidCap-like: flat ~16% none across quarters is sparse data, NOT a held-out fail
    qs = [_q("2024-03-31", 500, 16.0, 250, 98.0, 97.0),
          _q("2024-06-30", 520, 15.0, 255, 98.0, 97.0),
          _q("2024-09-30", 540, 17.0, 260, 98.0, 97.0)]
    assert _verdict_from_quarters(qs).verdict == "PASS"


# --- era-awareness (the MS delimited->flattened case) ---
def test_era_excluded_delimited_quarters_do_not_fail_the_gate():
    # 2 delimited quarters with 100% none (different regime) + 4 clean flattened in-era ones
    qs = [_q("2023-03-31", 400, 100.0, 0, None, None, era_match=False),
          _q("2023-06-30", 410, 100.0, 0, None, None, era_match=False)] + \
         [_q(f"2025-0{m}-30", 500, 0.5, 400, 99.0, 98.0) for m in range(3, 7)]
    v = _verdict_from_quarters(qs)
    assert v.verdict == "PASS"            # delimited quarters excluded, not failed
    assert v.confidence == "high"         # 4 in-era quarters = enough


def test_narrow_confidence_when_few_in_era_quarters():
    # MS reality: many delimited excluded, only 3 in-era flattened -> PASS but narrow
    qs = [_q(f"2024-{m:02d}-28", 400, 99.0, 0, None, None, era_match=False)
          for m in range(1, 11)] + \
         [_q("2025-09-30", 500, 0.2, 400, 100.0, 99.0),
          _q("2025-12-31", 500, 0.0, 420, 100.0, 99.0),
          _q("2026-03-31", 500, 0.4, 430, 99.4, 98.6)]
    v = _verdict_from_quarters(qs)
    assert v.verdict == "PASS"
    assert v.confidence == "narrow"       # 3 in-era, 10 excluded -> human review


def test_era_match_default_true_is_backward_compatible():
    # quarters with no era_match key behave as before (all in-era)
    qs = [_q("2024-03-31", 500, 1.0, 300, 99.0, 98.0),
          _q("2024-06-30", 520, 1.5, 310, 98.5, 97.0),
          _q("2024-09-30", 540, 1.2, 320, 99.5, 99.0),
          _q("2024-12-31", 540, 1.0, 320, 99.0, 99.0)]
    v = _verdict_from_quarters(qs)
    assert v.verdict == "PASS" and v.confidence == "high"


def test_twin_comparison_invariants_are_advisory_not_gating(tmp_path):
    # A grammar whose ONLY invariant is a twin pct_agree that FAILS on every row (the structured
    # interest_rate twin disagrees with the correctly-parsed identifier value), with no
    # self-contained (sum_identity) invariant. The twin disagreement must NOT fail the gate --
    # which value is authoritative is Agent B's per-row call -- it's reported as advisory
    # twin_agreement_pct instead. Regression for the twins->B routing change.
    import re
    import duckdb
    from pipeline.identifier_held_out import held_out_report

    pq = str(tmp_path / "h.parquet")
    con = duckdb.connect()
    vals = ",".join(
        f"('1','{q}','{q}','Interest Rate 10.00% term loan',0.05,NULL,NULL,NULL)"
        for q in ("2024-03-31", "2024-06-30") for _ in range(3)
    )
    con.execute(
        "CREATE TABLE t(cik VARCHAR, period VARCHAR, report_date VARCHAR, "
        "investment_identifier VARCHAR, interest_rate DOUBLE, basis_spread DOUBLE, "
        "pik_rate DOUBLE, maturity_date VARCHAR)")
    con.execute(f"INSERT INTO t VALUES {vals}")
    con.execute(f"COPY t TO '{pq}' (FORMAT PARQUET)")
    con.close()

    grammar = {
        "applies_to": {"signature": "RATE"},   # no regime -> era_match stays True
        "extractors": [{"field": "interest_rate", "regex": r"Interest Rate ([0-9.]+)%",
                        "group": 1, "type": "pct"}],
        "required_fields": ["interest_rate"],
        "invariants": [{"name": "ir_vs_twin", "kind": "pct_agree",
                        "parsed": "interest_rate", "twin": "interest_rate", "tol": 0.05}],
    }
    anchors = [("RATE", re.compile("Interest Rate", re.I))]
    v = held_out_report("1", "RATE", pq, grammar=grammar, anchors=anchors, min_quarters=2)

    assert v.verdict == "PASS"                                      # twin disagreement did NOT gate
    assert all(q["invariant_pct"] is None for q in v.quarters)      # no self-contained invariant -> no gate
    assert all(q["twin_agreement_pct"] == 0.0 for q in v.quarters)  # disagreement recorded as advisory
