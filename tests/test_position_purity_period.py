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


def _with_contexts(holding_context, holding_units, source_rows):
    """Blue Owl shape: units 989 in the current context and 989,000 in the comparative one; published 989,000."""
    holdings = _holdings().assign(src_context_id=holding_context, shares_held=holding_units)
    source = pd.concat([_source([period]).assign(src_context_id=context, shares_held=units)
                        for period, context, units in source_rows], ignore_index=True)
    diagnostics, _ = build_position_purity_diagnostics(holdings, source)
    return set(diagnostics["issue_family"]) if len(diagnostics) else set()


def test_a_row_takes_the_period_of_its_own_context_when_its_values_match_only_the_prior_fact():
    rows = [("2024-12-31", "c-1947", "989000.0"), ("2025-03-31", "c-568", "989.0")]
    assert "comparative_period" not in _with_contexts("c-568", "989000.0", rows)
    # published from the comparative context: still a prior-period row
    assert "comparative_period" in _with_contexts("c-1947", "989000.0", rows)
    # no context recorded on the row: the value match decides, as before
    assert "comparative_period" in _with_contexts("", "989000.0", rows)
