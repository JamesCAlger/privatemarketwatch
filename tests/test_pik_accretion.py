"""PIK accretion: is PIK being capitalized, and a Lincoln-style bad-PIK proxy from filings.

Lincoln International (Q1 2026 report): bad PIK is "an instance where a security was paying
only cash interest at close, even if a PIK toggle was present, but has implemented any level of
PIK interest as of each respective quarter-end". These tests pin the filings-only version.
"""
import pandas as pd
import pytest
from lxml import etree

from pipeline.bdc_filings import _parse_xbrl_contexts
from pipeline.bdc_position_pik import _extract_pik_evidence_facts
from pipeline.pik_accretion import (
    build_lincoln_summary,
    build_pik_accretion,
    build_pik_reconciliation,
    reported_quarterly_pik,
)

FUND = "0000000001"
OTHER = "0000000002"


def _rows(rows: list[dict]) -> pd.DataFrame:
    base = {
        "source": "bdc", "cik": FUND, "entity_name": "Fund", "position_id": "p1",
        "issuer_name": "Acme", "canonical_name": "Acme", "lien_position": "First Lien",
        "index_classification": "DIRECT_LENDING", "accounting_record_class": "parent_schedule",
        "fair_value": 100.0, "cost": 100.0, "principal_amount": 100.0,
        "principal_amount_currency": "USD", "pik_rate": None, "maturity_date": "2029-06-30",
        "bdc_acquisition_date": None, "nonaccrual_status": "unknown", "nport_is_paid_in_kind": None,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def _one(acc: pd.DataFrame, date: str, pid: str = "p1", cik: str = FUND) -> pd.Series:
    hit = acc[(acc["report_date"] == date) & (acc["position_id"] == pid) & (acc["cik"] == cik)]
    assert len(hit) == 1, hit
    return hit.iloc[0]


# --- payment evidence -------------------------------------------------------------------------

def test_principal_growing_at_the_pik_rate_is_accreting():
    h = _rows([
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["payment_evidence"] == "accreting"
    assert row["paying_now"]
    assert row["expected_growth"] == pytest.approx(0.04 * 90 / 365.25, rel=1e-6)


def test_flat_principal_with_pik_terms_is_flat_and_not_paying():
    h = _rows([
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1000.0},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["payment_evidence"] == "flat"
    assert not row["paying_now"]


def test_add_on_draw_is_undetermined_not_accreting():
    h = _rows([
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1300.0},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["payment_evidence"] == "undetermined"
    assert row["undetermined_reason"] == "principal_jump"


def test_first_observation_is_undetermined():
    h = _rows([{"report_date": "2026-03-31", "pik_rate": 4.0}])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["payment_evidence"] == "undetermined"
    assert row["undetermined_reason"] == "no_prior_quarter"


def test_non_usd_principal_is_undetermined():
    h = _rows([
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0, "principal_amount_currency": "EUR"},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9, "principal_amount_currency": "EUR"},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["undetermined_reason"] == "non_usd_principal"


def test_tagged_position_pik_income_is_confirmed_even_when_flat():
    h = _rows([
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1000.0},
    ])
    status = pd.DataFrame([{"cik": FUND, "position_id": "p1", "report_date": "2026-03-31",
                            "pik_current_status": "paying"}])
    row = _one(build_pik_accretion(h, status_df=status), "2026-03-31")
    assert row["payment_evidence"] == "confirmed_tagged"
    assert row["paying_now"]


def test_semiannual_capitalization_reads_as_accreting_over_two_quarters():
    h = _rows([
        {"report_date": "2025-09-30", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1018.0},
    ])
    acc = build_pik_accretion(h)
    assert _one(acc, "2025-12-31")["payment_evidence"] == "flat"
    row = _one(acc, "2026-03-31")
    assert row["payment_evidence"] == "accreting"
    assert row["accretion_window"] == "two_quarter"


def test_prior_quarter_is_the_funds_previous_filed_date_not_three_months_back():
    # 2025-09-30 + 3 months is 2025-12-30; the fund's next filed date is 2025-12-31.
    h = _rows([
        {"report_date": "2025-09-30", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1010.1},
    ])
    row = _one(build_pik_accretion(h), "2025-12-31")
    assert row["prior_report_date"] == "2025-09-30"
    assert row["payment_evidence"] == "accreting"


def test_rows_without_pik_terms_are_not_emitted():
    h = _rows([
        {"report_date": "2025-12-31", "pik_rate": None},
        {"report_date": "2026-03-31", "pik_rate": 0.0},
    ])
    assert build_pik_accretion(h).empty


def test_underlying_schedule_rows_are_excluded():
    h = _rows([
        {"report_date": "2026-03-31", "pik_rate": 4.0, "accounting_record_class": "underlying_schedule"},
    ])
    assert build_pik_accretion(h).empty


def test_timestamp_report_dates_come_out_as_yyyy_mm_dd():
    h = _rows([
        {"report_date": pd.Timestamp("2025-12-31"), "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": pd.Timestamp("2026-03-31"), "pik_rate": 4.0, "principal_amount": 1009.9},
    ])
    acc = build_pik_accretion(h)
    assert set(acc["report_date"]) == {"2025-12-31", "2026-03-31"}


# --- timing (state before PIK) ------------------------------------------------------------------

def test_pik_after_a_cash_only_quarter_is_started_after_cash_and_bad():
    h = _rows([
        {"report_date": "2025-09-30", "pik_rate": None, "principal_amount": 1000.0},
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["pik_timing"] == "started_after_cash"
    assert row["lincoln_class"] == "bad"


def test_pik_near_acquisition_date_is_at_origination_and_good():
    h = _rows([
        {"report_date": "2025-09-30", "position_id": "z", "pik_rate": None},  # fund history starts earlier
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0, "bdc_acquisition_date": "2025-11-15"},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9, "bdc_acquisition_date": "2025-11-15"},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["pik_timing"] == "at_origination"
    assert row["lincoln_class"] == "good"


def test_pik_at_first_observation_with_no_history_is_unknown_not_bad():
    h = _rows([
        {"report_date": "2025-09-30", "position_id": "z", "pik_rate": None},
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["pik_timing"] == "origin_unknown"
    assert row["lincoln_class"] == "unknown"


def test_pik_in_the_funds_first_filed_quarter_is_left_censored():
    h = _rows([
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["pik_timing"] == "left_censored"
    assert row["lincoln_class"] == "unknown"


def test_other_filer_cash_only_earlier_makes_started_after_cash_cross_filer():
    h = _rows([
        {"report_date": "2025-09-30", "position_id": "z", "pik_rate": None},
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9},
    ])
    ref = _rows([{"cik": OTHER, "position_id": "q9", "report_date": "2025-06-30", "pik_rate": None}])
    row = _one(build_pik_accretion(h, reference_df=ref), "2026-03-31")
    assert row["pik_timing"] == "started_after_cash_cross_filer"
    assert row["lincoln_class"] == "bad"


def test_other_filer_with_pik_earlier_stays_unknown():
    h = _rows([
        {"report_date": "2025-09-30", "position_id": "z", "pik_rate": None},
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9},
    ])
    ref = _rows([
        {"cik": OTHER, "position_id": "q9", "report_date": "2025-03-31", "pik_rate": None},
        {"cik": OTHER, "position_id": "q9", "report_date": "2025-06-30", "pik_rate": 4.0},
    ])
    row = _one(build_pik_accretion(h, reference_df=ref), "2026-03-31")
    assert row["pik_timing"] == "pik_seen_earlier_elsewhere"
    assert row["lincoln_class"] == "unknown"


def test_other_filer_with_a_different_maturity_is_not_the_same_loan():
    h = _rows([
        {"report_date": "2025-09-30", "position_id": "z", "pik_rate": None},
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9},
    ])
    ref = _rows([{"cik": OTHER, "position_id": "q9", "report_date": "2025-06-30", "pik_rate": None,
                  "maturity_date": "2031-01-15"}])
    row = _one(build_pik_accretion(h, reference_df=ref), "2026-03-31")
    assert row["pik_timing"] == "origin_unknown"


def test_lincoln_class_is_blank_when_not_paying_now():
    h = _rows([
        {"report_date": "2025-09-30", "pik_rate": None, "principal_amount": 1000.0},
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1000.0},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["payment_evidence"] == "flat"
    assert row["lincoln_class"] == ""
    assert row["flat_quarters"] == 2


def test_stress_flags_mark_below_90_and_drop():
    h = _rows([
        {"report_date": "2025-12-31", "pik_rate": 4.0, "principal_amount": 1000.0, "fair_value": 950.0},
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1009.9, "fair_value": 850.0},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["stress_mark_below_90"]
    assert row["stress_mark_drop_5pt"]
    assert not row["stress_nonaccrual"]


# --- Lincoln summary --------------------------------------------------------------------------

def _summary_input() -> pd.DataFrame:
    rows = []
    # four first-lien loans at 2026-03-31: one bad paying, one good paying, one flat, one cash-only
    for pid, q3, q4, q1, acq in [
        ("bad", None, 4.0, 4.0, None),
        ("good", None, None, 4.0, "2026-02-01"),
        ("flat", 4.0, 4.0, 4.0, None),
        ("cash", None, None, None, None),
    ]:
        principal = {"bad": [1000.0, 1000.0, 1009.9], "good": [None, None, 1000.0],
                     "flat": [1000.0, 1000.0, 1000.0], "cash": [1000.0, 1000.0, 1000.0]}[pid]
        for date, pik, par in zip(["2025-09-30", "2025-12-31", "2026-03-31"], [q3, q4, q1], principal):
            if par is None:
                continue
            rows.append({"report_date": date, "position_id": pid, "pik_rate": pik, "principal_amount": par,
                         "fair_value": par, "bdc_acquisition_date": acq})
    return _rows(rows)


def test_lincoln_summary_counts_and_shadow_default_rate():
    h = _summary_input()
    s = build_lincoln_summary(build_pik_accretion(h), h)
    row = s[(s["cik"] == FUND) & (s["report_date"] == "2026-03-31")].iloc[0]
    assert row["n_loans"] == 4
    assert row["n_paying_pik"] == 1 + 0  # 'good' is first seen this quarter: undetermined payment
    assert row["n_bad"] == 1
    assert row["pct_paying_pik_count"] == pytest.approx(25.0)
    assert row["bad_share_count"] == pytest.approx(100.0)
    assert row["shadow_default_count"] == pytest.approx(25.0)
    assert row["n_payment_undetermined"] == 1
    assert row["n_flat"] == 1


def test_lincoln_summary_has_cohort_row():
    h = _summary_input()
    s = build_lincoln_summary(build_pik_accretion(h), h)
    assert "ALL" in set(s["cik"])


def test_lincoln_summary_universe_is_first_lien_with_positive_value():
    h = pd.concat([_summary_input(), _rows([
        {"report_date": "2026-03-31", "position_id": "sub", "lien_position": "Second Lien"},
        {"report_date": "2026-03-31", "position_id": "undrawn", "fair_value": 0.0},
    ])])
    s = build_lincoln_summary(build_pik_accretion(h), h)
    row = s[(s["cik"] == FUND) & (s["report_date"] == "2026-03-31")].iloc[0]
    assert row["n_loans"] == 4


# --- fund-level reconciliation ----------------------------------------------------------------

def _evidence(rows: list[dict]) -> pd.DataFrame:
    base = {"cik": FUND, "accession_number": "A", "form_type": "10-Q", "context_id": "c",
            "dimensions_raw": "", "position_level": "False", "evidence_kind": "bdc_fund_level_pik_income"}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_reported_quarter_prefers_a_three_month_income_fact():
    ev = _evidence([
        {"report_date": "2026-06-30", "period_start": "2026-04-01", "period": "2026-06-30",
         "concept": "InterestIncomeOperatingPaidInKind", "amount": 30.0, "context_id": "q"},
        {"report_date": "2026-06-30", "period_start": "2026-01-01", "period": "2026-06-30",
         "concept": "InterestIncomeOperatingPaidInKind", "amount": 55.0, "context_id": "ytd"},
    ])
    r = reported_quarterly_pik(ev)
    row = r[(r["cik"] == FUND) & (r["report_date"] == "2026-06-30")].iloc[0]
    assert row["reported_pik"] == 30.0
    assert row["reported_method"] == "three_month_fact"


def test_reported_quarter_differences_year_to_date_cash_flow_facts():
    ev = _evidence([
        {"report_date": "2026-03-31", "accession_number": "Q1", "period_start": "2026-01-01",
         "period": "2026-03-31", "concept": "PaidInKindInterestNoncash", "amount": 20.0},
        {"report_date": "2026-06-30", "accession_number": "Q2", "period_start": "2026-01-01",
         "period": "2026-06-30", "concept": "PaidInKindInterestNoncash", "amount": 45.0},
    ])
    r = reported_quarterly_pik(ev)
    q2 = r[(r["cik"] == FUND) & (r["report_date"] == "2026-06-30")].iloc[0]
    assert q2["reported_pik"] == 25.0
    assert q2["reported_method"] == "ytd_difference"
    q1 = r[(r["cik"] == FUND) & (r["report_date"] == "2026-03-31")].iloc[0]
    assert q1["reported_pik"] == 20.0


def test_reported_quarter_ignores_dimensioned_and_cash_and_pik_combined_facts():
    ev = _evidence([
        {"report_date": "2026-06-30", "period_start": "2026-04-01", "period": "2026-06-30",
         "concept": "InterestIncomeOperatingPaidInKind", "amount": 30.0,
         "dimensions_raw": "investmentissueraffiliationaxis=InvestmentUnaffiliatedIssuerMember"},
        {"report_date": "2026-06-30", "period_start": "2026-04-01", "period": "2026-06-30",
         "concept": "InterestIncomeOperatingPaidInCashAndPaidInKind", "amount": 900.0, "context_id": "x"},
    ])
    assert reported_quarterly_pik(ev).empty


def test_reconciliation_compares_implied_and_observed_to_reported():
    h = _rows([
        {"report_date": "2026-03-31", "pik_rate": 4.0, "principal_amount": 1000.0},
        {"report_date": "2026-06-30", "pik_rate": 4.0, "principal_amount": 1009.97},
    ])
    acc = build_pik_accretion(h)
    ev = _evidence([{"report_date": "2026-06-30", "period_start": "2026-04-01", "period": "2026-06-30",
                     "concept": "InterestIncomeOperatingPaidInKind", "amount": 10.0}])
    rec = build_pik_reconciliation(acc, ev)
    row = rec[(rec["cik"] == FUND) & (rec["report_date"] == "2026-06-30")].iloc[0]
    assert row["implied_pik_terms"] == pytest.approx(1000.0 * 0.04 * 91 / 365.25)
    assert row["observed_accretion"] == pytest.approx(9.97)
    assert row["reported_pik"] == 10.0
    assert row["observed_to_reported"] == pytest.approx(0.997)


# --- extractor: period start ------------------------------------------------------------------

def test_evidence_extractor_records_period_start_for_duration_facts():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:test="http://example.com/test">
      <xbrli:context id="q">
        <xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period>
      </xbrli:context>
      <xbrli:context id="i">
        <xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
      </xbrli:context>
      <test:PaidInKindInterestIncome contextRef="q" unitRef="usd" decimals="0">99</test:PaidInKindInterestIncome>
      <test:InterestReceivablePaidInKind contextRef="i" unitRef="usd" decimals="0">5</test:InterestReceivablePaidInKind>
    </xbrli:xbrl>"""
    tree = etree.ElementTree(etree.fromstring(xml.encode("utf-8")))
    records = _extract_pik_evidence_facts(tree, _parse_xbrl_contexts(tree),
                                          {"cik": "100", "accession_number": "A", "report_date": "2024-03-31"})
    by_ctx = {r["context_id"]: r for r in records}
    assert by_ctx["q"]["period_start"] == "2024-01-01"
    assert by_ctx["q"]["period"] == "2024-03-31"
    assert by_ctx["i"]["period_start"] == ""


# --- wiring -----------------------------------------------------------------------------------

def test_fund_sandbox_runs_pik_after_the_rebuild_with_production_as_reference():
    import importlib
    trial = importlib.import_module("scripts.fund_ledger_trial")
    names = list(trial.STAGE_NAMES)
    assert names.index("rebuild") < names.index("pik") < names.index("validate")
    command = dict(trial.STAGES)["pik"]
    assert command[1:4] == ["-m", "pipeline.pik_accretion", "--with-status"]
    assert command[command.index("--reference-holdings") + 1].endswith("private_markets_holdings.csv")
    assert all(name.startswith(trial.NOT_SEEDED) for name in
               ("pik_accretion.csv", "pik_lincoln_summary.csv", "pik_reconciliation.csv"))


def test_rebound_after_a_principal_drop_is_not_semiannual_accretion():
    # ARCC WSHP FC at 2026-03-31 in sandbox pik1: 76.7m -> 23.5m -> 76.7m was read as two-quarter accretion.
    h = _rows([
        {"report_date": "2025-09-30", "pik_rate": 5.0, "principal_amount": 74.9},
        {"report_date": "2025-12-31", "pik_rate": 5.0, "principal_amount": 23.5},
        {"report_date": "2026-03-31", "pik_rate": 5.0, "principal_amount": 76.7},
    ])
    row = _one(build_pik_accretion(h), "2026-03-31")
    assert row["payment_evidence"] == "undetermined"
    assert row["undetermined_reason"] == "principal_jump"
