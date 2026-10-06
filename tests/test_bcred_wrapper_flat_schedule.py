"""Blackstone Private Credit Fund (CIK 1803498): a flat schedule with no category rows.

BCRED identifies a position by the issuer name, sometimes followed by ' - <instrument>'. A name
that matched a family word but no leaf marker fell through to '<family>_category_rollup' and the
row was dropped: 4 to 13 positions a quarter, 61.9M to 230.6M, equal to the fund's shortfall
against its filed total (2022-12-31 to 2025-09-30, fund sandbox 2026-10-06). Cash lines matched no
family at all, so the wrapper's cash markers never applied. Real filing identifiers.
"""
import pytest

from pipeline.bdc_xbrl_wrapper import classify_identifier

CIK = "0001803498"


@pytest.mark.parametrize("identifier,family", [
    ("CyrusOne Revolving Warehouse", "debt"),                                   # 130.9M at 2025-09-30
    ("Carlyle Global Market Strategies Euro CLO 2014-1 DAC - Subordinated Notes", "debt"),
    ("MidOcean Credit CLO XIX - Subordinated Notes", "debt"),
    ("Pikes Peak CLO 10 - Class ER", "clo"),
    ("Apidos CLO XXXVI - Class E", "clo"),
    ("Zoro - Series A Preferred Shares", "equity"),                             # 45.5M at 2025-09-30
    ("CyrusOne Revolving Warehouse | Non-Affiliated Issuer", "debt"),           # 2026-03-31 form
])
def test_named_rows_without_a_leaf_marker_are_positions(identifier, family):
    assert classify_identifier(CIK, identifier)["wrapper_disposition"] == family + "_position_leaf"


@pytest.mark.parametrize("identifier", [
    "Other Cash and Cash Equivalents",
    "Other Cash and Cash Equivalents, Emerald JV LP",
    "Emerald JV LP, Other Cash and Cash Equivalents",
    "Other Cash and Cash Equivalents | Verdelite JV LP",
    "Dreyfus Treasury Obligations Cash Management | Emerald JV LP",
])
def test_cash_lines_are_not_private_market_positions(identifier):
    assert classify_identifier(CIK, identifier)["wrapper_disposition"] == "non_private_market"


@pytest.mark.parametrize("identifier", [
    "Total Investments",
    "Total First Lien Debt",
])
def test_totals_stay_rollups(identifier):
    disposition = classify_identifier(CIK, identifier)["wrapper_disposition"]
    assert not disposition.endswith("_position_leaf")


def test_equity_leaf_is_unchanged():
    result = classify_identifier(CIK, "Mode Holdings, LP - Class A-2 Common Units")
    assert result["wrapper_disposition"] == "equity_position_leaf"
