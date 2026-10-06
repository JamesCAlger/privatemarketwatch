"""Apollo Debt Solutions (CIK 1837532): industry and issuer subtotal rows are not positions.

The filer tags a fair value for every industry heading ("Software") and every issuer heading
("Specialty Retail Carvana") with the investment identifier axis. Headings whose text carries no
company suffix used to match no wrapper family, so they kept no disposition and a few reached the
published holdings beside their own loans. Real filing identifiers; no production files touched.
"""
import pytest

from pipeline.bdc_xbrl_wrapper import classify_identifier

CIK = "0001837532"


@pytest.mark.parametrize("identifier", [
    "Specialty Retail Carvana",           # 2023-03-31, 34.09M = its two bonds (32.70M + 1.38M)
    "IT Services Anaplan",                # 2023-09-30, 147.43M = its term loan
    "MachineryJPW",                       # 2024-06-30
    "Financial Services PIB",             # 2025-03-31, 145.77M = its three loans
    "Financial Services Alpha FMC Actium Midco 3",
    "Software",
    "Health Care Providers & Services",
])
def test_heading_rows_are_aggregates(identifier):
    assert classify_identifier(CIK, identifier)["wrapper_disposition"] == "aggregate"


@pytest.mark.parametrize("identifier", [
    "US BANK GCTS0095",                   # 2025-03-31, 31.9M: filed cash equivalents 625.0M = 593.1M + 31.9M
    "Goldman Sachs Financial Square Government Fund Institutional",
])
def test_cash_equivalents_are_not_private_market_positions(identifier):
    assert classify_identifier(CIK, identifier)["wrapper_disposition"] == "non_private_market"


@pytest.mark.parametrize("identifier,family", [
    ("Special Retail Carvana Co. Investment Type Unsecured Debt - Corporate Bond Interest Rate 10.25%, "
     "Maturity Date 5/1/2030", "debt"),
    ("IT Services Anaplan Anaplan, Inc. Investment Type First Lien Secured Debt Interest Rate S+650, "
     "0.75% Floor Maturity Date 6/21/2029", "debt"),
    ("MachineryJPW JPW Industries Holding Corporation First Lien Secured Debt - Term Loan S+588, "
     "2.00% Floor 11/22/2028", "debt"),
    ("Household Durables Ergotron Ergotron Investments, LLC Common Equity - Equity Unit", "equity"),
])
def test_positions_keep_their_leaf_disposition(identifier, family):
    assert classify_identifier(CIK, identifier)["wrapper_disposition"] == family + "_position_leaf"
