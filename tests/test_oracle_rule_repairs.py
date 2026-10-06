"""Oracle rules repaired on 2026-10-06 (owner permission in session): each fired by construction.

Evidence and decisions: docs/investigations/v05_decision_log.md, entries D-001 to D-003.
Real counts come from the five-fund sandbox of that date.
"""
import pandas as pd

from pipeline.oracle_checks import (
    check_A07_pct_of_net_assets_sum,
    check_B02_unique_position_keys,
    check_E07_position_count_vs_filing,
)


def _detail(statuses, cik="0001838126", report_date="2026-03-31"):
    return pd.DataFrame([{"cik": cik, "report_date": report_date, "status": status,
                          "source_wrapper_disposition": "debt_position_leaf", "source_row_id": str(i)}
                         for i, status in enumerate(statuses)])


def _holdings(n, cik="0001838126", report_date="2026-03-31", **extra):
    return pd.DataFrame([{"cik": cik, "report_date": report_date, "fair_value": "1000000", **extra} for _ in range(n)])


# --- E07 -----------------------------------------------------------------------------------------

def test_e07_does_not_count_prior_period_or_repeated_dimension_rows():
    # HPS 2026-03-31: 838 comparative-period rows and 835 current positions; 835 published rows.
    detail = _detail(["excluded_comparative_period"] * 838 + ["matched"] * 827 + ["diagnostic_field_mismatch"] * 8)
    results = check_E07_position_count_vs_filing(detail, _holdings(835))
    assert [r.status for r in results] == ["pass"]
    assert "source=835 vs output=835" in results[0].message


def test_e07_ignores_rows_collapsed_as_repeated_dimension_paths():
    # Ares 2026-03-31: 1,456 rows are the same facts on a second dimension path.
    detail = _detail(["collapsed_duplicate_dimension_path"] * 1456 + ["matched"] * 1412 + ["diagnostic_field_mismatch"] * 7,
                     cik="0001287750")
    results = check_E07_position_count_vs_filing(detail, _holdings(1419, cik="0001287750"))
    assert [r.status for r in results] == ["pass"]


def test_e07_still_fails_when_positions_are_missing_from_the_output():
    detail = _detail(["matched"] * 80 + ["missing_from_pipeline"] * 20)
    results = check_E07_position_count_vs_filing(detail, _holdings(80))
    assert [r.status for r in results] == ["fail"]
    assert "source=100 vs output=80" in results[0].message


def test_e07_still_fails_when_the_output_has_extra_rows():
    results = check_E07_position_count_vs_filing(_detail(["matched"] * 100), _holdings(130))
    assert [r.status for r in results] == ["fail"]


def test_e07_without_a_status_column_keeps_the_leaf_count():
    detail = _detail(["matched"] * 10).drop(columns=["status"])
    results = check_E07_position_count_vs_filing(detail, _holdings(10))
    assert [r.status for r in results] == ["pass"]


# --- A07 -----------------------------------------------------------------------------------------

def test_a07_skips_a_fund_quarter_that_reports_no_percent():
    # Ares, Apollo and HPS tag the percent per industry only: 0 of 36,595 / 14,577 / 14,418 source rows carry one.
    holdings = _holdings(800, pct_of_net_assets="")
    results = check_A07_pct_of_net_assets_sum(holdings)
    assert [r.status for r in results] == ["skip"]
    assert "no pct_of_net_assets reported" in results[0].message


def test_a07_still_fails_on_a_reported_sum_out_of_range():
    # Blue Owl 2023-06-30 before the scale fix: reported percents summed to 5,084.
    holdings = _holdings(100, pct_of_net_assets="50.843")
    results = check_A07_pct_of_net_assets_sum(holdings)
    assert [r.status for r in results] == ["fail"]


def test_a07_still_fails_when_a_few_rows_report_a_tiny_sum():
    # A filing with some percents present but summing far below 50 is not "nothing reported".
    holdings = pd.concat([_holdings(5, pct_of_net_assets="0.1"), _holdings(95, pct_of_net_assets="")], ignore_index=True)
    assert [r.status for r in check_A07_pct_of_net_assets_sum(holdings)] == ["fail"]


# --- B02 -----------------------------------------------------------------------------------------

def _keyed(rows):
    base = {"cik": "0001837532", "report_date": "2026-03-31", "position_key": "primeflight acquisition llc first lien term loan",
            "fair_value": "34380000", "principal_amount": "34900000", "maturity_date": "2029-05-01", "basis_spread": "4.75",
            "interest_rate_reported": "", "accounting_scope_id": "0001837532|parent"}
    return pd.DataFrame([{**base, **row} for row in rows])


def test_b02_passes_two_tranches_that_share_a_key_but_not_their_terms():
    # Apollo 2026-03-31, PrimeFlight Acquisition: S+475 34.4M and S+525 9.9M. The key drops rate and maturity.
    frame = _keyed([{}, {"fair_value": "9900000", "principal_amount": "9925000", "basis_spread": "5.25"}])
    assert [r.status for r in check_B02_unique_position_keys(frame)] == ["pass"]


def test_b02_passes_the_same_position_in_the_fund_schedule_and_in_a_jv_schedule():
    # BCRED 2026-03-31: Red Griffin ParentCo Class A Common Units in the parent schedule and in Emerald JV LP.
    frame = _keyed([{}, {"accounting_scope_id": "0001803498|Emerald JV LP"}])
    assert [r.status for r in check_B02_unique_position_keys(frame)] == ["pass"]


def test_b02_still_fails_on_a_repeated_fact():
    frame = _keyed([{}, {}])
    results = check_B02_unique_position_keys(frame)
    assert [r.status for r in results] == ["fail"]
    assert "2 duplicate position keys" in results[0].message


# --- C01 and dl_rate_fill (decision D-012) -------------------------------------------------------

def _loans(funded_with_rate, funded_without, undrawn):
    rows = ([{"fair_value": "1000000", "interest_rate": "9.5", "basis_spread": "5.0"}] * funded_with_rate
            + [{"fair_value": "1000000", "interest_rate": "", "basis_spread": ""}] * funded_without
            + [{"fair_value": "-20000", "interest_rate": "", "basis_spread": ""}] * undrawn
            + [{"fair_value": "0", "interest_rate": "", "basis_spread": ""}] * undrawn)
    return pd.DataFrame([{"cik": "0001838126", "report_date": "2026-03-31", "asset_category": "LOAN",
                          "index_classification": "DIRECT_LENDING", **row} for row in rows])


def test_c01_measures_rate_fill_on_funded_loans():
    # HPS: 76 pct of loan rows carry a rate, 92 pct of funded ones; the gap is undrawn lines at zero or negative value.
    from pipeline.oracle_checks import check_C01_debt_has_rate
    results = check_C01_debt_has_rate(_loans(funded_with_rate=92, funded_without=8, undrawn=15))
    assert [r.status for r in results] == ["pass"]
    assert "92.0% of 100 funded debt rows" in results[0].message


def test_c01_still_fails_when_funded_loans_lack_rates():
    from pipeline.oracle_checks import check_C01_debt_has_rate
    results = check_C01_debt_has_rate(_loans(funded_with_rate=60, funded_without=40, undrawn=0))
    assert [r.status for r in results] == ["fail"]


def test_dl_rate_fill_gate_is_funded_direct_lending_rows():
    import duckdb
    from scripts.shadow_weak_engine import RULES
    rule = next(r for r in RULES if r.name == "dl_rate_fill")
    con = duckdb.connect()
    # the engine reads the holdings file, where an empty cell is NULL
    con.register("weak_base", _loans(funded_with_rate=92, funded_without=8, undrawn=15).replace("", None))
    total, present = con.execute(f"SELECT count(*), count(*) FILTER (WHERE {rule.present_sql}) FROM weak_base WHERE ({rule.gate_sql})").fetchone()
    assert (total, present) == (100, 92)


# --- D07 (decision D-015) ------------------------------------------------------------------------

def _rated(quarter, rates):
    return pd.DataFrame([{"cik": "0001837532", "report_date": quarter, "interest_rate": str(rate)} for rate in rates])


def test_d07_skips_a_median_taken_over_a_handful_of_rows():
    # Apollo files spreads; 13 rows carried a rate at 2023-09-30 (median 6.5) and 15 at 2023-12-31 (9.75).
    from pipeline.oracle_checks import check_D07_rate_distribution_stability
    frame = pd.concat([_rated("2023-09-30", [6.5] * 13), _rated("2023-12-31", [9.75] * 15)], ignore_index=True)
    results = check_D07_rate_distribution_stability(frame)
    assert [r.status for r in results] == ["skip"]


def test_d07_still_fails_on_a_shift_across_a_full_schedule():
    from pipeline.oracle_checks import check_D07_rate_distribution_stability
    frame = pd.concat([_rated("2023-09-30", [6.5] * 200), _rated("2023-12-31", [9.75] * 200)], ignore_index=True)
    results = check_D07_rate_distribution_stability(frame)
    assert [r.status for r in results] == ["fail"]
