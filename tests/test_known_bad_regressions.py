"""Known-bad historical data-quality regression tests.

These tests are intentionally small and local. They pin named mechanisms that
previously created silent holdings/classification errors without requiring SEC
downloads or broad pipeline rebuilds.
"""

from pipeline.bdc_identifier import _is_bdc_aggregate_row
from pipeline.classification import (
    _classify_index,
    _classify_nport_issuer,
)


def test_aggregate_headers_filtered_but_entity_signals_preserved():
    assert _is_bdc_aggregate_row("177.4% Common Equity/Partnership Interests/Warrants")
    assert _is_bdc_aggregate_row("First Lien Debt")
    assert not _is_bdc_aggregate_row("95.93% Company LLC Industry Software")
    assert not _is_bdc_aggregate_row("89.2% FedHC InvestCo LP")


def test_goldman_hierarchy_category_labels_do_not_survive_as_positions():
    assert _is_bdc_aggregate_row("Senior Secured Debt")
    assert _is_bdc_aggregate_row("Second Lien Debt")
    assert _is_bdc_aggregate_row("Subordinated Debt")
    assert not _is_bdc_aggregate_row("Acme Corp - Second Lien Term Loan")


def test_nuss_corporate_borrower_remains_non_government():
    issuer_category = _classify_nport_issuer("NUSS")
    assert issuer_category == "OTHER"
    assert _classify_index("LOAN", "CORPORATE", "Acme Software LLC", "", "LON") == "DIRECT_LENDING"
    assert _classify_index("DEBT", "GOVERNMENT", "U.S. Treasury Bill", "", "NUSS") == "CASH"


def test_lp_spv_name_is_not_automatically_a_fund():
    assert _classify_index(
        "EQUITY_COMMON",
        "CORPORATE",
        "AffiniPay Intermediate Holdings LLC, L.P.",
        "",
        "EC",
    ) == "COMMON_EQUITY"
    assert _classify_index(
        "OTHER",
        "FUND",
        "TPG Partners VIII, L.P.",
        "",
        "EC",
    ) == "PRIVATE_EQUITY_FUND"


def test_multi_dimension_duplicate_key_is_position_level_not_borrower_level():
    first_key = (
        "0000000100", "2024-03-31", "acme corp",
        "first lien term loan", 1000000.0, 1000000.0, 0.0,
    )
    duplicate_dimension_key = (
        "0000000100", "2024-03-31", "acme corp",
        "first lien term loan", 1000000.0, 1000000.0, 0.0,
    )
    distinct_tranche_key = (
        "0000000100", "2024-03-31", "acme corp",
        "second lien term loan", 1000000.0, 1000000.0, 0.0,
    )
    assert first_key == duplicate_dimension_key
    assert first_key != distinct_tranche_key
