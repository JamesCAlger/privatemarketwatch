"""Tests for pipeline.rate_convention (per-CIK cash_leg vs all_in classifier)."""

import pandas as pd
import pytest

from pipeline.rate_convention import (apply_convention_overrides,
                                      build_rate_convention, classify_cik)


# --------------------------------------------------------------------- pure decision rule

def _stats(**kw):
    base = {"n_pik_rows": 50, "n_dual": 40, "n_viol": 0,
            "n_cash_phrase": 0, "n_incl_phrase": 0,
            "income_r_median": None, "income_quarters": 0,
            "income_votes_allin": 0, "income_votes_cash": 0,
            "n_nearcap": 0, "s5_rows_d0": 0, "s5_rows_allin": 0,
            "unstable": False}
    base.update(kw)
    return base


def test_ordering_violations_convict_cash_leg():
    r = classify_cik(_stats(n_viol=20))
    assert r["convention"] == "cash_leg"
    assert r["confidence"] == "high"          # 50% >= 40%
    assert r["basis"] == "ordering_violations"


def test_moderate_violations_medium_confidence():
    r = classify_cik(_stats(n_viol=10))       # 25% in [20%, 40%)
    assert (r["convention"], r["confidence"]) == ("cash_leg", "medium")


def test_zero_violations_alone_prove_nothing():
    r = classify_cik(_stats())
    assert r["convention"] == "unknown"
    assert r["basis"] == "no_signal"


def test_low_rate_but_many_violations_convicts():
    # Barings/Golub shape: most positions have cash > PIK, so the violation
    # RATE is low, but dozens of genuine violations still prove cash-leg.
    r = classify_cik(_stats(n_dual=300, n_viol=20))     # 6.7%, count 20
    assert (r["convention"], r["confidence"]) == ("cash_leg", "medium")


def test_few_scattered_violations_below_count_floor_do_not_convict():
    # 2 violating rows in 40 dual rows (5%) is parse-noise territory
    r = classify_cik(_stats(n_dual=40, n_viol=2))
    assert r["convention"] == "unknown"


def test_income_votes_allin_decide_all_in():
    r = classify_cik(_stats(income_votes_allin=4, income_quarters=4, income_r_median=0.1))
    assert (r["convention"], r["basis"]) == ("all_in", "income_reconciliation")


def test_income_votes_cash_decide_cash_leg():
    r = classify_cik(_stats(income_votes_cash=4, income_quarters=4, income_r_median=0.9))
    assert r["convention"] == "cash_leg"


def test_income_midband_votes_are_uninformative():
    # 4 informative quarters, all mid-band (no votes either side)
    r = classify_cik(_stats(income_quarters=4, income_r_median=0.5))
    assert r["convention"] == "unknown"


def test_income_needs_min_votes():
    r = classify_cik(_stats(income_votes_allin=1, income_quarters=1))
    assert r["convention"] == "unknown"


def test_income_split_votes_no_dominance_is_unknown():
    # 3 vs 2 fails the 2x dominance requirement
    r = classify_cik(_stats(income_votes_allin=3, income_votes_cash=2, income_quarters=5))
    assert r["convention"] == "unknown"


def test_violations_beat_income_conflict_to_unknown():
    # S1 convicts cash_leg but income says all_in -> conflicting evidence, no guess
    r = classify_cik(_stats(n_viol=20, income_votes_allin=4, income_quarters=4))
    assert (r["convention"], r["basis"]) == ("unknown", "s1_conflict")


def test_phrasing_agreement_raises_confidence():
    r = classify_cik(_stats(income_votes_cash=4, income_quarters=4, n_cash_phrase=10))
    assert (r["convention"], r["confidence"]) == ("cash_leg", "high")


def test_phrasing_conflict_with_income_is_unknown():
    r = classify_cik(_stats(income_votes_cash=4, income_quarters=4, n_incl_phrase=10))
    assert (r["convention"], r["basis"]) == ("unknown", "numeric_s3_conflict")


def test_phrasing_alone_is_low_confidence():
    r = classify_cik(_stats(n_incl_phrase=5))
    assert (r["convention"], r["confidence"], r["basis"]) == ("all_in", "low", "phrasing_only")


def test_immaterial_pik_is_no_pik():
    r = classify_cik(_stats(n_pik_rows=3, n_viol=2, n_dual=3))
    assert r["convention"] == "no_pik"


def test_unstable_violations_escalate_to_unknown():
    r = classify_cik(_stats(n_viol=20, unstable=True))
    assert (r["convention"], r["basis"]) == ("unknown", "s1_unstable")


def test_statistical_ceiling_convicts_all_in():
    r = classify_cik(_stats(n_dual=100, n_viol=0, n_nearcap=12))
    assert (r["convention"], r["confidence"], r["basis"]) == \
        ("all_in", "medium", "statistical_ceiling")


def test_ceiling_needs_nearcap_mass():
    r = classify_cik(_stats(n_dual=100, n_viol=0, n_nearcap=3))
    assert r["convention"] == "unknown"


def test_ceiling_blocked_by_cash_phrasing_conflict():
    r = classify_cik(_stats(n_dual=100, n_viol=0, n_nearcap=12, n_cash_phrase=10))
    assert (r["convention"], r["basis"]) == ("unknown", "ceiling_conflict")


def test_ceiling_needs_zero_violations():
    r = classify_cik(_stats(n_dual=100, n_viol=1, n_nearcap=12))
    assert r["convention"] == "unknown"


def test_s5_allin_signature_decides_all_in():
    r = classify_cik(_stats(s5_rows_allin=15))
    assert (r["convention"], r["confidence"], r["basis"]) == \
        ("all_in", "medium", "spread_arithmetic")


def test_s5_d0_dominance_is_ambiguous_not_cash_evidence():
    # ir - spread - bench ~ 0 holds under BOTH conventions ("incl" filers quote
    # an all-in spread too) -- must never produce a cash vote
    r = classify_cik(_stats(s5_rows_d0=30))
    assert r["convention"] == "unknown"


def test_s5_conflicts_with_income_to_unknown():
    r = classify_cik(_stats(s5_rows_allin=15, income_votes_cash=4, income_quarters=4))
    assert (r["convention"], r["basis"]) == ("unknown", "s2_s5_conflict")


def test_s5_and_income_agreement_is_high_confidence():
    r = classify_cik(_stats(s5_rows_allin=15, income_votes_allin=4, income_quarters=4))
    assert (r["convention"], r["confidence"], r["basis"]) == \
        ("all_in", "high", "income_and_spread")


# --------------------------------------------------------------------- aggregation e2e

def _holdings(rows):
    # rows: (source, cik, report_date, interest_rate, pik_rate, principal_amount,
    #        bdc_investment_identifier[, basis_spread])
    rows = [r if len(r) == 8 else (*r, None) for r in rows]
    return pd.DataFrame(rows, columns=["source", "cik", "report_date", "interest_rate",
                                       "pik_rate", "principal_amount",
                                       "bdc_investment_identifier", "basis_spread"])


def _income(rows):
    # rows: (cik, report_date, duration_months, interest_income[, total_investment_income])
    rows = [r if len(r) == 5 else (*r, None) for r in rows]
    return pd.DataFrame(rows, columns=["cik", "report_date", "duration_months",
                                       "interest_income", "total_investment_income"])


def test_e2e_cash_leg_filer_via_violations():
    rows = [("bdc", "0001000001", "2025-03-31", 6.7, 7.6, 1_000_000.0,
             f"Borrower {i} | 6.7% Cash, 7.6% PIK") for i in range(12)]
    out = build_rate_convention(_holdings(rows), _income([]))
    assert list(out["convention"]) == ["cash_leg"]
    assert list(out["basis"]) == ["ordering_violations"]


def test_e2e_all_in_filer_via_income():
    # interest 10% all-in incl 4% PIK: income matches base alone (r ~= 0)
    rows = []
    for q in ("2024-12-31", "2025-03-31", "2025-06-30"):
        rows += [("bdc", "0001000002", q, 10.0, 4.0, 1_000_000.0,
                  f"Borrower {i}") for i in range(12)]
    # base per quarter = 12 * 10%/4 * 1m = 300k; all-in filer income ~= base
    inc = _income([("0001000002", q, 3, 300_000.0)
                   for q in ("2024-12-31", "2025-03-31", "2025-06-30")])
    out = build_rate_convention(_holdings(rows), inc)
    assert list(out["convention"]) == ["all_in"]
    assert list(out["basis"]) == ["income_reconciliation"]


def test_e2e_cash_leg_filer_via_income():
    # interest 10% cash + 4% PIK on top: income ~= base + pik_add (r ~= 1)
    rows = []
    for q in ("2024-12-31", "2025-03-31"):
        rows += [("bdc", "0001000003", q, 10.0, 4.0, 1_000_000.0,
                  f"Borrower {i}") for i in range(12)]
    # base = 300k, pik_add = 120k -> income 420k
    inc = _income([("0001000003", q, 3, 420_000.0)
                   for q in ("2024-12-31", "2025-03-31")])
    out = build_rate_convention(_holdings(rows), inc)
    assert list(out["convention"]) == ["cash_leg"]


def test_e2e_phrasing_false_positive_guard_company_named_cash():
    # "Cash Convertors" in the issuer text must NOT create a cash-phrasing vote
    rows = [("bdc", "0001000004", "2025-03-31", 12.0, 3.0, None,
             f"Cash Convertors Intl unit {i} 3.0% PIK") for i in range(8)]
    out = build_rate_convention(_holdings(rows), _income([]))
    assert int(out.loc[0, "n_cash_phrase"]) == 0
    assert list(out["convention"]) == ["unknown"]


def test_e2e_incl_phrasing_votes_all_in():
    rows = [("bdc", "0001000005", "2025-03-31", 10.5, 2.5, None,
             f"Borrower {i} 10.5% (incl. 2.5% PIK)") for i in range(8)]
    out = build_rate_convention(_holdings(rows), _income([]))
    assert list(out["convention"]) == ["all_in"]
    assert list(out["basis"]) == ["phrasing_only"]


def test_e2e_suppress_phrasing_for_heldout_eval():
    rows = [("bdc", "0001000006", "2025-03-31", 10.5, 2.5, None,
             f"Borrower {i} 10.5% (incl. 2.5% PIK)") for i in range(8)]
    out = build_rate_convention(_holdings(rows), _income([]), suppress_phrasing=True)
    assert list(out["convention"]) == ["unknown"]


def test_violations_conflict_with_incl_phrasing_to_unknown():
    r = classify_cik(_stats(n_viol=20, n_incl_phrase=10))
    assert (r["convention"], r["basis"]) == ("unknown", "s1_conflict")


def test_e2e_ceiling_convicts_large_zero_violation_filer():
    # 70 dual rows, PIK legs near the interest cap, zero violations -> all_in
    rows = [("bdc", "0001000011", "2025-03-31", 12.0, 11.0, 1_000_000.0,
             f"Borrower {i}") for i in range(70)]
    out = build_rate_convention(_holdings(rows), _income([]))
    assert list(out["convention"]) == ["all_in"]
    assert list(out["basis"]) == ["statistical_ceiling"]


def test_e2e_spread_arithmetic_detects_all_in():
    # bench implied from 30 non-PIK floating rows: ir 9.3 = spr 5.0 + 4.3.
    # PIK rows: ir 12.3 = spread 5.0 + bench 4.3 + pik 3.0 -> unambiguous all-in
    rows = [("bdc", "0001000012", "2025-03-31", 9.3, None, 1_000_000.0,
             f"NonPik {i}", 5.0) for i in range(30)]
    rows += [("bdc", "0001000012", "2025-03-31", 12.3, 3.0, 1_000_000.0,
              f"PikRow {i}", 5.0) for i in range(10)]
    out = build_rate_convention(_holdings(rows), _income([]))
    assert int(out.loc[0, "s5_rows_allin"]) >= 8
    assert list(out["convention"]) == ["all_in"]
    assert list(out["basis"]) == ["spread_arithmetic"]


def test_e2e_spread_matching_cash_interpretation_stays_unknown():
    # PIK rows where ir = spread + bench exactly: ambiguous (all-in spread or
    # cash-leg ir) -- must NOT be labeled either way from S5 alone
    rows = [("bdc", "0001000013", "2025-03-31", 9.3, None, 1_000_000.0,
             f"NonPik {i}", 5.0) for i in range(30)]
    rows += [("bdc", "0001000013", "2025-03-31", 9.3, 3.0, 1_000_000.0,
              f"PikRow {i}", 5.0) for i in range(10)]
    out = build_rate_convention(_holdings(rows), _income([]))
    assert list(out["convention"]) == ["unknown"]


def test_e2e_negative_income_ratio_does_not_vote_all_in():
    # base alone overshoots income (r < INCOME_R_FLOOR): a measurement problem,
    # not all-in evidence -- must not create an income vote
    rows = []
    for q in ("2024-12-31", "2025-03-31", "2025-06-30"):
        rows += [("bdc", "0001000010", q, 10.0, 4.0, 1_000_000.0,
                  f"Borrower {i}") for i in range(12)]
    # base = 300k/quarter but actual income only 200k -> r = -0.83
    inc = _income([("0001000010", q, 3, 200_000.0)
                   for q in ("2024-12-31", "2025-03-31", "2025-06-30")])
    out = build_rate_convention(_holdings(rows), inc)
    assert int(out.loc[0, "income_votes_allin"]) == 0
    assert list(out["convention"]) == ["unknown"]


def test_e2e_equal_rates_are_not_violations():
    # 100%-PIK positions legitimately report interest_rate == pik_rate under
    # all-in storage; equality (and float noise around it) must not convict.
    rows = [("bdc", "0001000009", "2025-03-31", 13.75, 13.75, 1_000_000.0,
             f"Borrower {i} 13.75% PIK") for i in range(15)]
    out = build_rate_convention(_holdings(rows), _income([]))
    assert int(out.loc[0, "n_viol"]) == 0
    assert list(out["convention"]) == ["unknown"]


def test_e2e_nport_rows_ignored():
    rows = [("nport", "0001000007", "2025-03-31", 6.0, 8.0, 1_000_000.0,
             "irrelevant PIK") for _ in range(20)]
    out = build_rate_convention(_holdings(rows), _income([]))
    assert len(out) == 0


def test_e2e_income_coverage_band_rejects_partial_extraction():
    # Holdings capture only a sliver of the book: base/income far below 0.4 ->
    # the quarter must NOT produce an income vote (r would be wildly inflated)
    rows = [("bdc", "0001000008", "2025-03-31", 10.0, 4.0, 1_000_000.0, "Borrower")
            for _ in range(6)]
    for q in ("2024-12-31", "2025-06-30"):
        rows += [("bdc", "0001000008", q, 10.0, 4.0, 1_000_000.0, "B")
                 for _ in range(6)]
    # base = 150k/quarter but fund income says 5m -> coverage 3% -> skip
    inc = _income([("0001000008", q, 3, 5_000_000.0)
                   for q in ("2024-12-31", "2025-03-31", "2025-06-30")])
    out = build_rate_convention(_holdings(rows), inc)
    assert int(out.loc[0, "income_quarters"]) == 0
    assert list(out["convention"]) == ["unknown"]


# --------------------------------------------------------------------- override merge

def _rc_df(convention="unknown", basis="no_signal"):
    return pd.DataFrame([{
        "cik": "0001812554", "convention": convention, "confidence": "low",
        "basis": basis, "n_pik_rows": 100, "n_dual": 0, "n_viol": 0,
        "n_cash_phrase": 0, "n_incl_phrase": 0, "income_r_median": None,
        "income_quarters": 0, "income_votes_allin": 0, "income_votes_cash": 0,
        "n_nearcap": 0, "s5_rows_d0": 0, "s5_rows_allin": 0,
        "unstable": False, "reasons": "r", "method_version": "1.0"}])


def test_override_supersedes_unknown():
    out = apply_convention_overrides(
        _rc_df(), {"1812554": {"convention": "all_in", "verify_tier": "HIGH"}})
    r = out.iloc[0]
    assert (r["convention"], r["confidence"], r["basis"]) == \
        ("all_in", "high", "adjudicated_override")


def test_override_contradiction_demotes_not_overrides():
    # deterministic layer now convicts cash_leg; a stale all_in override must
    # demote to unknown and re-enter the queue, never silently win
    out = apply_convention_overrides(
        _rc_df(convention="cash_leg", basis="ordering_violations"),
        {"1812554": {"convention": "all_in", "verify_tier": "HIGH"}})
    r = out.iloc[0]
    assert (r["convention"], r["basis"]) == ("unknown", "demoted_override")
    assert "STALE OVERRIDE" in r["reasons"]


def test_override_agreement_corroborates():
    out = apply_convention_overrides(
        _rc_df(convention="all_in", basis="statistical_ceiling"),
        {"1812554": {"convention": "all_in", "verify_tier": "MEDIUM"}})
    r = out.iloc[0]
    assert (r["convention"], r["confidence"], r["basis"]) == \
        ("all_in", "high", "statistical_ceiling")


def test_indeterminate_override_is_terminal_and_distinct():
    out = apply_convention_overrides(
        _rc_df(), {"1812554": {"convention": "indeterminate", "verify_tier": "MEDIUM"}})
    r = out.iloc[0]
    assert (r["convention"], r["basis"]) == ("indeterminate", "adjudicated_indeterminate")


def test_no_pik_rows_never_touched_by_overrides():
    out = apply_convention_overrides(
        _rc_df(convention="no_pik", basis="immaterial"),
        {"1812554": {"convention": "all_in", "verify_tier": "HIGH"}})
    assert out.iloc[0]["convention"] == "no_pik"


# --------------------------------------------------------------------- S0 tag fingerprint

from pipeline.rate_convention import s0_from_fingerprint


def test_s0_cash_dominance_with_label_ok_convicts_high():
    s0 = s0_from_fingerprint(wb=7, wc=2109, triple=0, sum_ok=0,
                             label_status="ok_cash")
    assert (s0["s0_vote"], s0["s0_confidence"]) == ("cash_leg", "high")


def test_s0_cash_dominance_without_labels_is_medium():
    s0 = s0_from_fingerprint(wb=0, wc=4746, triple=0, sum_ok=0,
                             label_status="no_labels")
    assert (s0["s0_vote"], s0["s0_confidence"]) == ("cash_leg", "medium")


def test_s0_label_contradiction_abstains():
    # First Eagle pattern: 100% cash-concept wins but labels contradict
    s0 = s0_from_fingerprint(wb=0, wc=2769, triple=0, sum_ok=0,
                             label_status="contradiction")
    assert s0["s0_vote"] is None
    assert "misuse" in s0["s0_reason"]


def test_s0_sum_proof_convicts_all_in():
    # WhiteHorse pattern: bare == cash + pik on 589/594 triple contexts
    s0 = s0_from_fingerprint(wb=5713, wc=2, triple=594, sum_ok=589)
    assert (s0["s0_vote"], s0["s0_confidence"]) == ("all_in", "high")


def test_s0_sum_proof_needs_low_cash_contamination():
    # sum holds but 20% of stored contexts came from the cash concept
    s0 = s0_from_fingerprint(wb=400, wc=100, triple=100, sum_ok=95)
    assert s0["s0_vote"] is None
    assert s0["s0_mixed"] is True


def test_s0_mixed_semantics_flags_without_vote():
    # BlackRock pattern: stored column mixes Total Coupon and Spread Cash
    s0 = s0_from_fingerprint(wb=6032, wc=1104, triple=1007, sum_ok=32)
    assert s0["s0_vote"] is None
    assert s0["s0_mixed"] is True
    assert "per-row" in s0["s0_reason"]


def test_s0_below_volume_floor_is_silent():
    s0 = s0_from_fingerprint(wb=10, wc=30, triple=0, sum_ok=0)
    assert s0["s0_vote"] is None
    assert s0["s0_mixed"] is False


def test_classify_s0_cash_leg_resolves_no_signal():
    # Gladstone pattern: classifier had no signal; S0 concept proof decides
    r = classify_cik(_stats(s0_vote="cash_leg", s0_confidence="high",
                            s0_reason="stored column won by PaidInCash"))
    assert (r["convention"], r["confidence"], r["basis"]) == \
        ("cash_leg", "high", "tag_fingerprint")


def test_classify_s0_all_in_resolves_ceiling_conflict_stats():
    r = classify_cik(_stats(s0_vote="all_in", s0_confidence="high",
                            s0_reason="sum proof"))
    assert (r["convention"], r["basis"]) == ("all_in", "tag_fingerprint")


def test_classify_s0_all_in_conflicts_with_s1_to_unknown():
    r = classify_cik(_stats(n_viol=20, s0_vote="all_in",
                            s0_confidence="high", s0_reason="sum proof"))
    assert (r["convention"], r["basis"]) == ("unknown", "s0_s1_conflict")


def test_classify_s0_cash_leg_conflicts_with_ceiling_to_unknown():
    r = classify_cik(_stats(n_dual=100, n_viol=0, n_nearcap=12,
                            s0_vote="cash_leg", s0_confidence="high",
                            s0_reason="concept dominance"))
    assert (r["convention"], r["basis"]) == ("unknown", "s0_ceiling_conflict")


def test_classify_s0_cash_leg_agrees_with_s1_high_confidence():
    r = classify_cik(_stats(n_viol=20, s0_vote="cash_leg",
                            s0_confidence="medium", s0_reason="concept dominance"))
    assert (r["convention"], r["confidence"], r["basis"]) == \
        ("cash_leg", "high", "tag_fingerprint")
    assert any("corroborate" in x for x in r["reasons"])


def test_classify_s0_cash_leg_conflicts_with_income_allin_to_unknown():
    r = classify_cik(_stats(income_votes_allin=4, income_quarters=4,
                            s0_vote="cash_leg", s0_confidence="high",
                            s0_reason="concept dominance"))
    assert (r["convention"], r["basis"]) == ("unknown", "s0_conflict")


def test_classify_s0_mixed_annotates_but_does_not_decide():
    r = classify_cik(_stats(n_viol=20, s0_mixed=True,
                            s0_reason="mixed semantics"))
    assert (r["convention"], r["basis"]) == ("cash_leg", "ordering_violations")
    assert any("mixed semantics" in x for x in r["reasons"])


def test_classify_no_s0_keys_unchanged_behavior():
    # stats dicts without S0 keys must classify exactly as before
    r = classify_cik(_stats(n_viol=20))
    assert (r["convention"], r["basis"]) == ("cash_leg", "ordering_violations")


def test_build_rate_convention_s0_optin(monkeypatch):
    holdings = pd.DataFrame({
        "source": ["BDC"] * 60,
        "cik": ["0001143513"] * 60,
        "report_date": ["2025-12-31"] * 60,
        "interest_rate": [10.0] * 60,
        "pik_rate": [2.0] * 60,
        "principal_amount": [1e6] * 60,
        "basis_spread": [None] * 60,
        "bdc_investment_identifier": ["Acme Corp Term Loan"] * 60,
    })
    income = pd.DataFrame(columns=["cik", "report_date", "interest_income",
                                   "total_investment_income", "duration_months"])
    s0 = {1143513: {"s0_vote": "cash_leg", "s0_confidence": "high",
                    "s0_mixed": False, "s0_reason": "concept dominance"}}
    out = build_rate_convention(holdings, income, s0=s0)
    row = out[out["cik"] == "0001143513"].iloc[0]
    assert (row["convention"], row["basis"]) == ("cash_leg", "tag_fingerprint")
    assert row["s0_vote"] == "cash_leg"
    # without s0 the same frames must not pick up any S0 signal
    out2 = build_rate_convention(holdings, income)
    row2 = out2[out2["cik"] == "0001143513"].iloc[0]
    assert row2["basis"] != "tag_fingerprint"
    assert row2["s0_vote"] == ""


def test_classify_s0_all_in_survives_phrasing_only_conflict():
    # WhiteHorse: sum proof + clean violations, but "x% cash" phrasing rows.
    # Phrasing describes the printed decomposition; S0 measured it directly.
    r = classify_cik(_stats(n_dual=300, n_viol=0, n_cash_phrase=11,
                            s0_vote="all_in", s0_confidence="high",
                            s0_reason="sum proof"))
    assert (r["convention"], r["basis"]) == ("all_in", "tag_fingerprint")
    assert any("non-blocking" in x for x in r["reasons"])


def test_classify_s0_all_in_blocked_by_numeric_income_cash():
    r = classify_cik(_stats(income_votes_cash=4, income_quarters=4,
                            s0_vote="all_in", s0_confidence="high",
                            s0_reason="sum proof"))
    assert (r["convention"], r["basis"]) == ("unknown", "s0_conflict")


def test_classify_s0_cash_leg_survives_incl_phrasing():
    r = classify_cik(_stats(n_incl_phrase=5, s0_vote="cash_leg",
                            s0_confidence="high", s0_reason="concept dominance"))
    assert (r["convention"], r["basis"]) == ("cash_leg", "tag_fingerprint")
