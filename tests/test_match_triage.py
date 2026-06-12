"""Tests for pipeline.match_triage module.

Covers:
- Five heuristic flags individually
- No-flag clean pair
- CIK and tier filtering
- Instrument sub-type parser
"""

import pandas as pd
import pytest

from pipeline.match_triage import (
    DEFAULT_TRIAGE_TIERS,
    parse_instrument_subtype,
    triage_match_quality,
)


def _make_matches(overrides=None):
    """Build a minimal match DataFrame with one C_normalized_name pair."""
    row = {
        "cik": "0001572694",
        "match_method": "C_normalized_name",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Senior Secured Term Loan",
        "end_issuer_name": "Acme Corp - Senior Secured Term Loan",
        "begin_fair_value": 10000000,
        "end_fair_value": 9500000,
        "entity_name": "Test Fund",
        "source": "bdc",
    }
    if overrides:
        row.update(overrides)
    return pd.DataFrame([row])


def _make_holdings(begin_overrides=None, end_overrides=None):
    """Build a minimal holdings DataFrame with begin/end rows.

    Default: consistent classification, maturity, description, and rate.
    """
    begin = {
        "cik": "0001572694",
        "report_date": "2024-09-30",
        "issuer_name": "Acme Corp - Senior Secured Term Loan",
        "source": "bdc",
        "fair_value": 10000000,
        "index_classification": "Direct Lending",
        "maturity_date": "2027-06-15",
        "instrument_description": "Senior Secured First Lien Term Loan",
        "interest_rate": 9.5,
        "basis_spread": 5.25,
    }
    end = {
        "cik": "0001572694",
        "report_date": "2024-12-31",
        "issuer_name": "Acme Corp - Senior Secured Term Loan",
        "source": "bdc",
        "fair_value": 9500000,
        "index_classification": "Direct Lending",
        "maturity_date": "2027-06-15",
        "instrument_description": "Senior Secured First Lien Term Loan",
        "interest_rate": 9.5,
        "basis_spread": 5.25,
    }
    if begin_overrides:
        begin.update(begin_overrides)
    if end_overrides:
        end.update(end_overrides)
    return pd.DataFrame([begin, end])


# --- Individual flag tests ---


def test_triage_classification_flip_flagged():
    """Different index_classification triggers flag_classification_flip."""
    matches = _make_matches()
    holdings = _make_holdings(
        begin_overrides={"index_classification": "Direct Lending"},
        end_overrides={"index_classification": "Opportunistic"},
    )
    result = triage_match_quality(matches, holdings)
    assert len(result) == 1
    assert result.iloc[0]["flag_classification_flip"] == True
    assert result.iloc[0]["triage_flags"] >= 1
    assert result.iloc[0]["triage_severity"] == "high"


def test_triage_subtype_mismatch_flagged():
    """term_loan vs revolver triggers flag_subtype_mismatch."""
    matches = _make_matches({
        "end_issuer_name": "Acme Corp - Revolving Credit Facility",
    })
    holdings = _make_holdings(
        begin_overrides={"instrument_description": "Senior Secured First Lien Term Loan"},
        end_overrides={
            "issuer_name": "Acme Corp - Revolving Credit Facility",
            "instrument_description": "Senior Secured Revolving Credit Facility",
        },
    )
    result = triage_match_quality(matches, holdings)
    assert len(result) == 1
    assert result.iloc[0]["flag_subtype_mismatch"] == True


def test_triage_maturity_gap_flagged():
    """>365 day maturity gap triggers flag_maturity_gap."""
    matches = _make_matches()
    holdings = _make_holdings(
        begin_overrides={"maturity_date": "2027-06-15"},
        end_overrides={"maturity_date": "2029-01-15"},  # ~18 month gap
    )
    result = triage_match_quality(matches, holdings)
    assert len(result) == 1
    assert result.iloc[0]["flag_maturity_gap"] == True


def test_triage_fv_ratio_extreme_flagged():
    """>10x FV ratio triggers flag_fv_ratio_extreme."""
    matches = _make_matches({
        "begin_fair_value": 10000000,
        "end_fair_value": 500000,  # 20x ratio
    })
    holdings = _make_holdings(
        end_overrides={"fair_value": 500000},
    )
    result = triage_match_quality(matches, holdings)
    assert len(result) == 1
    assert result.iloc[0]["flag_fv_ratio_extreme"] == True


def test_triage_rate_discontinuity_flagged():
    """>5 pct pt rate difference triggers flag_rate_discontinuity."""
    matches = _make_matches()
    holdings = _make_holdings(
        begin_overrides={"basis_spread": 5.25},
        end_overrides={"basis_spread": 12.00},  # 6.75 pct pt gap
    )
    result = triage_match_quality(matches, holdings)
    assert len(result) == 1
    assert result.iloc[0]["flag_rate_discontinuity"] == True


def test_triage_no_flags_when_consistent():
    """Matching pair with consistent attributes has 0 flags."""
    matches = _make_matches()
    holdings = _make_holdings()
    result = triage_match_quality(matches, holdings)
    assert len(result) == 1
    assert result.iloc[0]["triage_flags"] == 0
    assert result.iloc[0]["triage_severity"] == ""


# --- Filtering tests ---


def test_triage_cik_filter():
    """Only returns pairs for requested CIK."""
    row_a = {
        "cik": "0001572694",
        "match_method": "C_normalized_name",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan",
        "end_issuer_name": "Acme Corp - Term Loan",
        "begin_fair_value": 10000000,
        "end_fair_value": 9500000,
    }
    row_b = dict(row_a, cik="0001111111", begin_issuer_name="Beta Corp",
                 end_issuer_name="Beta Corp")
    matches = pd.DataFrame([row_a, row_b])
    holdings = _make_holdings()
    result = triage_match_quality(matches, holdings, cik="0001572694")
    assert len(result) == 1
    assert result.iloc[0]["cik"] == "0001572694"


def test_triage_tier_filter():
    """Only returns C/D/E pairs by default, excludes B2."""
    row_c = {
        "cik": "0001572694",
        "match_method": "C_normalized_name",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan",
        "end_issuer_name": "Acme Corp - Term Loan",
        "begin_fair_value": 10000000,
        "end_fair_value": 9500000,
    }
    row_b = dict(row_c, match_method="B2_exact_name")
    matches = pd.DataFrame([row_c, row_b])
    holdings = _make_holdings()
    result = triage_match_quality(matches, holdings)
    assert len(result) == 1
    assert result.iloc[0]["match_method"] == "C_normalized_name"


# --- Instrument sub-type parser tests ---


def test_parse_subtype_term_loan():
    assert parse_instrument_subtype("Senior Secured First Lien Term Loan") == "TERM_LOAN"


def test_parse_subtype_revolver():
    assert parse_instrument_subtype("Revolving Credit Facility") == "REVOLVER"


def test_parse_subtype_ddtl():
    assert parse_instrument_subtype("Delayed Draw Term Loan") == "DDTL"


def test_parse_subtype_equity():
    assert parse_instrument_subtype("Common Equity") == "EQUITY"


def test_parse_subtype_warrant():
    assert parse_instrument_subtype("Warrants") == "WARRANT"


def test_parse_subtype_empty():
    assert parse_instrument_subtype("") == ""
    assert parse_instrument_subtype("Senior Secured Note") == ""
