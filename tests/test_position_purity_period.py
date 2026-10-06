"""PP03 (prior-period row) must not fire on a current row whose values did not change (decision D-011).

HPS 2025-03-31, Calabrio, Inc. 1: fair value 1,152,000, cost 1,152,000, principal 2,687,000 in both the
2024-12-31 comparative context and the 2025-03-31 context of filing 0001838126-25-000031. The published
row comes from the 2025-03-31 context (c-562), but the period lookup took the earliest matching period.
"""
import pandas as pd

from pipeline.position_purity import build_position_purity_diagnostics


def _source(periods):
    return pd.DataFrame([{"cik": "0001838126", "report_date": "2025-03-31", "period": period,
                          "accession_number": "0001838126-25-000031", "investment_identifier": "Calabrio, Inc. 1",
                          "dimensions_raw": "investmentidentifieraxis=Calabrio, Inc. 1", "fair_value": "1152000.0",
                          "cost": "1152000.0", "principal_amount": "2687000.0", "shares_held": ""} for period in periods])


def _holdings():
    return pd.DataFrame([{"source": "bdc", "cik": "0001838126", "entity_name": "HPS Corporate Lending Fund",
                          "report_date": "2025-03-31", "accession_number": "0001838126-25-000031",
                          "issuer_name": "Calabrio, Inc. 1", "instrument_description": "",
                          "bdc_investment_identifier": "Calabrio, Inc. 1",
                          "bdc_dimensions_raw": "investmentidentifieraxis=Calabrio, Inc. 1", "fair_value": "1152000.0",
                          "cost": "1152000.0", "principal_amount": "2687000.0", "shares_held": "", "cusip": "", "isin": ""}])


def _families(source):
    diagnostics, _ = build_position_purity_diagnostics(_holdings(), source)
    return set(diagnostics["issue_family"]) if len(diagnostics) else set()


def test_unchanged_position_present_in_both_periods_is_current():
    assert "comparative_period" not in _families(_source(["2024-12-31", "2025-03-31"]))


def test_row_found_only_in_the_prior_period_is_still_flagged():
    assert "comparative_period" in _families(_source(["2024-12-31"]))
