import pandas as pd
import pytest

from pipeline.bdc_xbrl_wrapper import (
    add_bdc_xbrl_wrapper_columns,
    classify_identifier,
    supported_prefixes_for_cik,
    supported_wrapper_ciks,
)


def test_trinity_bare_debt_identifier_is_issuer_rollup():
    bare = "Portfolio Company Debt Securities- Europe Industrials Aledia, Inc."
    leaf = (
        "Portfolio Company Debt Securities- Europe Industrials Aledia, Inc."
        "Type of Investment Equipment Financing Investment Date March 31, 2022 "
        "Maturity Date April 1, 2025 Interest Rate Fixed interest rate 9.0%; EOT 7.0%"
    )

    rollup = classify_identifier("1786108", bare)
    child = classify_identifier("0001786108", leaf)

    assert rollup["wrapper_family"] == "debt"
    assert rollup["wrapper_disposition"] == "debt_issuer_rollup"
    assert rollup["wrapper_rule_id"] == "TRINITY_DEBT_ISSUER_ROLLUP_V3"
    assert child["wrapper_disposition"] == "debt_position_leaf"
    assert child["wrapper_rule_id"] == "TRINITY_DEBT_LEAF_V3"
    assert rollup["wrapper_parent_key"] == child["wrapper_parent_key"]
    assert child["wrapper_position_key"] != rollup["wrapper_parent_key"]
    assert child["wrapper_structured_leaf_key"]


def test_trinity_leaf_position_keys_distinguish_terms():
    first = classify_identifier(
        "0001786108",
        "Portfolio Company Debt Securities- Canada Construction Technology Nexii Building "
        "Solutions, Inc.Type of Investment Secured Loan Investment Date January 2, 2024 "
        "Maturity Date June 30, 2026 Interest Rate Variable interest rate S + 9.00%",
    )
    second = classify_identifier(
        "0001786108",
        "Portfolio Company Debt Securities- Canada Construction Technology Nexii Building "
        "Solutions, Inc.Type of Investment Secured Loan Investment Date February 2, 2024 "
        "Maturity Date July 31, 2026 Interest Rate Variable interest rate S + 9.50%",
    )

    assert first["wrapper_parent_key"] == second["wrapper_parent_key"]
    assert first["wrapper_position_key"] != second["wrapper_position_key"]
    assert first["wrapper_structured_leaf_key"] != second["wrapper_structured_leaf_key"]


def test_trinity_rollup_taxonomy_distinguishes_category_issuer_and_total():
    category = classify_identifier(
        "0001786108",
        "Portfolio Company Debt Securities- Europe Space Technology",
    )
    issuer = classify_identifier(
        "0001786108",
        "Portfolio Company Debt Securities- United States Space Technology Hadrian Automation, Inc.",
    )
    total = classify_identifier(
        "0001786108",
        "Portfolio Company Debt Securities- Sub-total: Education Technology",
    )

    assert category["wrapper_disposition"] == "debt_category_rollup"
    assert issuer["wrapper_disposition"] == "debt_issuer_rollup"
    assert total["wrapper_disposition"] == "debt_total_rollup"


def test_trinity_warrant_prefix_gets_family_specific_signatures():
    issuer = classify_identifier(
        "0001786108",
        "Portfolio Company Warrant Investments Applied Digital Corporation",
    )
    leaf = classify_identifier(
        "0001786108",
        "Portfolio Company Warrant Investments Applied Digital Corporation "
        "Type of Investment Warrant Investment Date January 1, 2024 Expiration Date January 1, 2034",
    )

    assert issuer["wrapper_family"] == "warrant"
    assert issuer["wrapper_disposition"] == "warrant_issuer_rollup"
    assert leaf["wrapper_disposition"] == "warrant_position_leaf"
    assert leaf["wrapper_structured_leaf_key"]


def test_wrapper_columns_are_empty_for_other_ciks():
    df = pd.DataFrame({
        "cik": ["0000000100"],
        "investment_identifier": [
            "Portfolio Company Debt Securities- Europe Industrials Aledia, Inc."
        ],
    })

    wrapped = add_bdc_xbrl_wrapper_columns(df, identifier_col="investment_identifier")

    assert wrapped.loc[0, "wrapper_disposition"] == ""
    assert wrapped.loc[0, "wrapper_parent_key"] == ""


def test_registry_exposes_supported_ciks_and_prefixes():
    assert "0001786108" in supported_wrapper_ciks()
    assert "0001920145" in supported_wrapper_ciks()
    assert "0001572694" in supported_wrapper_ciks()
    assert "0001508655" in supported_wrapper_ciks()
    assert "0001925309" in supported_wrapper_ciks()
    assert "Portfolio Company Debt Securities" in supported_prefixes_for_cik("1786108")
    assert "Investment Debt Investments" in supported_prefixes_for_cik("0001920145")


def test_goldman_wrapper_classifies_hierarchical_debt_leaf():
    row = classify_identifier(
        "0001920145",
        "Investment Debt Investments - 179.3% Belgium - 0.3% "
        "1st Lien/Senior Secured Debt - 0.3% Ranch Bidco B.V. "
        "Industry Biotechnology Interest Rate 6.79% Reference Rate and Spread E + 4.75% "
        "Maturity 1/28/33",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "GS_PRIVATE_CREDIT_DEBT_LEAF_V3"
    assert row["wrapper_position_key"]


def test_goldman_bdc_reuses_goldman_hierarchy():
    row = classify_identifier(
        "0001572694",
        "Investment 1st Lien/Senior Secured Debt - 103.97% "
        "CST Buyer Company (dba Intoxalock) Industry Diversified Consumer Services "
        "Interest Rate 11.95% Reference Rate and Spread S + 6.75% Maturity 11/01/28",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "GS_BDC_DEBT_LEAF_V1"
    assert row["wrapper_position_key"]


def test_goldman_wrapper_normalizes_mojibake_dash_and_duplicate_prefix():
    row = classify_identifier(
        "0001920145",
        "Investment Debt InveInvestment Debt Investments - 179.3% Italy - 1.0% "
        "1st Lien/Senior Secured Debt - 0.9% INK (BC) BIDCO S.R.L. "
        "Industry Software Interest Rate 7.14% Reference Rate and Spread E + 5.00% "
        "Initial Acquisition Date 04/15/25 Maturity 04/11/32",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_position_key"].startswith("investment debt investments")


def test_sixth_street_shared_wrapper_classifies_debt_leaf_for_both_ciks():
    identifier = (
        "Debt Investments Business Services Elements Finco Limited "
        "First-lien loan ($4,069 par, due 4/2031) Initial Acquisition Date 04/29/2024 "
        "Reference Rate and Spread SOFR + 4.97% Interest Rate 9.33%"
    )

    specialty = classify_identifier("0001508655", identifier)
    lending_partners = classify_identifier("0001925309", identifier)

    assert specialty["wrapper_disposition"] == "debt_position_leaf"
    assert lending_partners["wrapper_disposition"] == "debt_position_leaf"
    assert specialty["wrapper_rule_id"] == "SIXTH_STREET_SPECIALTY_DEBT_LEAF_V1"
    assert lending_partners["wrapper_rule_id"] == "SIXTH_STREET_LENDING_PARTNERS_DEBT_LEAF_V1"


def test_sixth_street_shared_wrapper_classifies_equity_leaf():
    row = classify_identifier(
        "0001508655",
        "Equity and Other Investments Business Services Artisan Topco LP "
        "Class A Preferred Units (2,117,264 units) Initial Acquisition Date 11/7/2023",
    )

    assert row["wrapper_family"] == "equity"
    assert row["wrapper_disposition"] == "equity_position_leaf"


def test_fidelity_wrapper_classifies_hierarchical_debt_leaf():
    row = classify_identifier(
        "0001920453",
        "Investments Investments - non-controlled / non-affiliate First Lien Debt "
        "Aerospace & Defense Insight Technology Operation LLC Revolving Credit Facility "
        "Maturity Date 03/31/2031",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "FIDELITY_PRIVATE_CREDIT_DEBT_LEAF_V1"


def test_fidelity_wrapper_classifies_mutual_funds_as_non_private_market():
    row = classify_identifier(
        "0001920453",
        "Investments Investments -- non-controlled/ affiliate Fixed Income Mutual Funds "
        "Mutual Funds Fidelity Floating Rate Central Fund Mutual Fund",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "non_private_market"


def test_saratoga_wrapper_marks_category_like_pct_rows_as_aggregate():
    row = classify_identifier(
        "0001377936",
        "Affiliate investments - 13.4% - Corporate Education Software",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "aggregate"


def test_saratoga_wrapper_classifies_lowercase_non_control_leaf():
    row = classify_identifier(
        "0001377936",
        "Non-control/Non-affiliate investments - 229.3% - Avantra - IT Services - "
        "First Lien Term Loan (3M USD TERM SOFR+7.97%), 12.29% Cash, 9/20/2029",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"
    assert row["wrapper_rule_id"] == "SARATOGA_MIXED_LEAF_V1"
    assert row["wrapper_position_key"]


def test_saratoga_wrapper_canonicalizes_stripped_output_identifier():
    source = classify_identifier(
        "0001377936",
        "Non-control/Non-affiliate investments - 229.3% - Avantra - IT Services - "
        "First Lien Term Loan (3M USD TERM SOFR+7.97%), 12.29% Cash, 9/20/2029",
    )
    output = classify_identifier(
        "0001377936",
        "229.3% - Avantra - IT Services - First Lien Term Loan "
        "(3M USD TERM SOFR+7.97%), 12.29% Cash, 9/20/2029",
    )

    assert output["wrapper_disposition"] == "mixed_position_leaf"
    assert output["wrapper_position_key"] == source["wrapper_position_key"]
    assert output["wrapper_parent_key"] == source["wrapper_parent_key"]


def test_saratoga_wrapper_classifies_bare_industry_rows_as_aggregate():
    row = classify_identifier("0001377936", "Alternative Investment Management Software")

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "aggregate"
    assert row["wrapper_rule_id"] == "SARATOGA_MIXED_AGGREGATE_V1"


def test_saratoga_wrapper_classifies_bare_affiliation_category_as_aggregate():
    row = classify_identifier(
        "0001377936",
        "Corporate Education Software - Affiliate investments",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "aggregate"


def test_saratoga_wrapper_columns_apply_to_bare_category_rows():
    df = pd.DataFrame({
        "cik": ["0001377936"],
        "investment_identifier": ["Education Services - Control investments"],
    })

    wrapped = add_bdc_xbrl_wrapper_columns(df, identifier_col="investment_identifier")

    assert wrapped.loc[0, "wrapper_disposition"] == "aggregate"


def test_saratoga_wrapper_classifies_terminal_pct_total_as_rollup():
    row = classify_identifier("0001377936", "TOTAL INVESTMENTS - 256.5%")

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_total_rollup"


def test_saratoga_wrapper_classifies_non_control_subtotal_as_rollup():
    row = classify_identifier(
        "0001377936",
        "Sub Total Non-control/Non-affiliate investments",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_total_rollup"


def test_saratoga_wrapper_classifies_cash_total_as_non_private_market():
    row = classify_identifier("0001377936", "Total cash and cash equivalents")

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "non_private_market"


def test_wrapper_does_not_treat_cash_plus_pik_coupon_as_cash():
    row = classify_identifier(
        "0001377936",
        "Non-control/Non-affiliate investments - 229.3% - Avantra - IT Services - "
        "First Lien Term Loan (3M USD TERM SOFR+7.97%), 12.29% Cash + 2.00% PIK, "
        "9/20/2029",
    )

    assert row["wrapper_disposition"] == "mixed_position_leaf"


def test_saratoga_wrapper_classifies_terminal_instrument_without_issuer_as_leaf():
    row = classify_identifier(
        "0001377936",
        "Non-control/Non-affiliate investments - 229.3% - Direct Selling Software - Common Units",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"
    assert row["wrapper_position_key"]


# ---------------------------------------------------------------------------
# GS Private Credit (0001920145)
# ---------------------------------------------------------------------------

def test_gs_private_credit_debt_leaf_classified():
    """Standard GS Private Credit debt leaf with Interest Rate field."""
    row = classify_identifier(
        "0001920145",
        "Investment 1st Lien/Senior Secured Debt - 93.10% United States - 85.3% "
        "Acme Corp Industry Software Interest Rate 11.58% Reference Rate and "
        "Spread S + 5.75% Maturity 01/15/2028",
    )
    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"


def test_gs_private_credit_equity_leaf_classified():
    """GS Private Credit equity position via Investment Equity Securities prefix."""
    row = classify_identifier(
        "0001920145",
        "Investment Equity Securities - 0.1% United States - 0.1% Common Stock "
        "- 0.1% RPC ABC Investment Holdings LLC Aerospace & Defense",
    )
    assert row["wrapper_family"] == "equity"
    assert row["wrapper_disposition"] == "equity_position_leaf"


def test_gs_private_credit_country_only_is_aggregate():
    """Bare country name matched via fallback should classify as aggregate."""
    for country in ("Canada", "Switzerland", "United Kingdom"):
        row = classify_identifier("0001920145", country)
        assert row["wrapper_disposition"] == "aggregate", f"{country} not aggregate"


def test_gs_private_credit_investments_total_is_aggregate():
    """Portfolio-level 'Investments - X%' totals should be aggregate."""
    row = classify_identifier("0001920145", "Investments - 103.97%")
    assert row["wrapper_disposition"] == "aggregate"


def test_gs_private_credit_money_market_is_non_private():
    """Goldman Sachs Financial Square Government Fund is non-private-market."""
    row = classify_identifier(
        "0001920145",
        "Investment United States - 9.1% Goldman Sachs Financial Square "
        "Government Fund - Institutional Shares",
    )
    assert row["wrapper_disposition"] == "non_private_market"


def test_gs_private_credit_debt_investments_country_is_aggregate():
    """'Debt Investments United States' is aggregate marker."""
    row = classify_identifier("0001920145", "Debt Investments United States")
    assert row["wrapper_disposition"] == "aggregate"


def test_gs_private_credit_total_investments_is_rollup():
    """'Total Investments - X%' should be debt_total_rollup."""
    row = classify_identifier("0001920145", "Total Investments - 128.77%")
    assert row["wrapper_disposition"] == "debt_total_rollup"


def test_gs_private_credit_truncated_prefix_classified():
    """Truncated 'nvestment Debt Investments' prefix still classifies."""
    row = classify_identifier(
        "0001920145",
        "nvestment Debt Investments - 179.3% United States - 170.1% "
        "Acme Corp Industry Software Interest Rate 11.0% "
        "Reference Rate and Spread S + 5.50% Maturity 06/30/2028",
    )
    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"


# --- identifier_parser config tests ---

def test_identifier_parser_loads_from_gs_json():
    """identifier_parser section loads correctly from GS wrapper JSON."""
    from pipeline.staging_bdc import _load_identifier_parsers
    parsers = _load_identifier_parsers()
    gs_cik = "0001920145"
    assert gs_cik in parsers, f"GS CIK {gs_cik} not in parsers"
    cfg = parsers[gs_cik]
    assert cfg["type"] == "hierarchical_pct"
    assert "issuer_boundary_keywords" in cfg
    assert "Industry" in cfg["issuer_boundary_keywords"]
    assert "country_list" in cfg
    assert "United States" in cfg["country_list"]


def test_identifier_parser_missing_section_is_fine():
    """Wrapper JSON without identifier_parser section should not error."""
    from pipeline.staging_bdc import _load_identifier_parsers
    parsers = _load_identifier_parsers()
    # Most CIKs do not have identifier_parser; just verify the function
    # returns a dict without errors.
    assert isinstance(parsers, dict)


# ---------------------------------------------------------------------------
# PIMCO Capital Solutions BDC Corp. (0001905824)
# ---------------------------------------------------------------------------

PIMCO_CIK = "0001905824"


def test_pimco_debt_first_lien_leaf():
    """First lien senior secured term loan with SOFR spread is classified as debt leaf."""
    ident = (
        "Debt Investments | First Lien Senior Secured | Technology | "
        "MRI Software, LLC Term Loan | SOFR + 4.750 % | 8.450 % | 02/10/2028"
    )
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]  # non-empty


def test_pimco_debt_second_lien_leaf():
    """Second lien debt position is classified as debt leaf."""
    ident = (
        "Debt Investments | Second Lien Senior Secured | Technology | "
        "Mavenir Systems, Inc. 2L Term Loan | N/A | 12.000% PIK | 07/26/2030"
    )
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_pimco_senior_unsecured_leaf():
    """Senior unsecured PIK note is classified as debt leaf."""
    ident = (
        "Debt Investments | Senior Unsecured | Technology | GCOM | "
        "N/A | 17.000 % PIK | 02/16/2029"
    )
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_pimco_corporate_bond_leaf():
    """Corporate bond with 144A is classified as debt leaf."""
    ident = (
        "Corporate Bonds | Automotive | "
        "Rivian Holdings/Auto LLC 144A | SOFR + 5.625% | 11.490% | 10/15/2026"
    )
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_pimco_equity_common_stock():
    """Common stock equity position is classified as equity leaf."""
    ident = "Common Stock | Chemicals | K2 Propco Class S Units"
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_pimco_equity_common_stocks_variant():
    """Older 'Common Stocks' prefix variant is also classified as equity."""
    ident = "Common Stocks | Retailers | West Marine/Rising Tide Holdings, Inc."
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "equity"


def test_pimco_warrant_leaf():
    """Warrant position under Warrants prefix is classified correctly."""
    ident = "Warrants | Technology | GCOM | 8/11/2033"
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "warrant"
    assert result["wrapper_disposition"] == "warrant_position_leaf"


def test_pimco_warrant_under_debt_prefix():
    """Warrants nested under 'Debt Investments | Warrants' are classified as debt family.

    These lack typical debt leaf markers (SOFR, interest rate, maturity keywords)
    so they classify as category rollup, which is acceptable -- the staging pipeline
    handles them separately via the Warrants prefix variant.
    """
    ident = (
        "Debt Investments | Warrants | Technology | GCOM | 08/11/2033"
    )
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_category_rollup"


def test_pimco_aggregate_total_investments():
    """'Total Investments' is classified as aggregate."""
    result = classify_identifier(PIMCO_CIK, "Total Investments")
    assert result["wrapper_disposition"] == "aggregate_total_rollup"


def test_pimco_aggregate_total_first_lien():
    """Industry subtotal under first lien is classified as aggregate."""
    ident = (
        "Debt Investments | First Lien Senior Secured | Total First Lien Senior Secured"
    )
    result = classify_identifier(PIMCO_CIK, ident)
    assert "aggregate" in result["wrapper_disposition"] or "rollup" in result["wrapper_disposition"]


def test_pimco_aggregate_total_debt():
    """'Total Debt Investments' is classified as aggregate."""
    ident = "Debt Investments | Total Debt Investments"
    result = classify_identifier(PIMCO_CIK, ident)
    assert "aggregate" in result["wrapper_disposition"] or "rollup" in result["wrapper_disposition"]


def test_pimco_short_term_treasury_leaf():
    """Short-term T-bill under 'Short-Term Investments' prefix is classified as debt."""
    ident = (
        "Short-Term Investments | U.S. Treasury Bills | U.S. Treasury Bill | "
        "N/A | 3.756% | 10/14/2025"
    )
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "debt"


def test_pimco_truncated_lien_prefix():
    """Truncated 'First Lie' (missing 'n') is still classified as debt."""
    ident = (
        "Debt Investments | First LieSenior Secured | Technology | "
        "MH Sub I, LLC Term Loan | SOFR + 4.250 % | 7.918 % | 05/03/2028"
    )
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_pimco_preferred_stock():
    """Preferred stock is classified as equity."""
    ident = "Preferred Stock | Energy | Mustang Express, Series A"
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_pimco_no_space_pipe_prefix():
    """'Debt Investments |First Lien' (no space after pipe) is classified as debt."""
    ident = (
        "Debt Investments |First Lien Senior Secured | Technology | "
        "Arctic Wolf Networks, Inc. Term Loan| SOFR + 5.750%| 10.058%| 02/04/2030"
    )
    result = classify_identifier(PIMCO_CIK, ident)
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_pimco_reference_rate_metadata():
    """Standalone reference rate rows are classified via fallback as metadata."""
    result = classify_identifier(PIMCO_CIK, "One Month SOFR")
    assert result["wrapper_family"] == "metadata"


# ---------------------------------------------------------------------------
# MSD Investment Corp. (CIK 0001849894) - dispatch + staging wrapper
# ---------------------------------------------------------------------------
MSD_CIK = "0001849894"


def test_msd_debt_leaf_first_lien():
    """First lien debt with issuer and rate detail is a leaf position."""
    ident = (
        "Investments Investments - non-controlled/non-affiliated "
        "First Lien Debt Aerospace & Defense "
        "Frontgrade Technologies Inc. Reference Rate and Spread S + 4.50% "
        "Interest Rate 8.90% Maturity Date 1/9/2030"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_msd_debt_leaf_delayed_draw():
    """Delayed draw term loan is classified as leaf."""
    ident = (
        "Investments Investments - non-controlled/non-affiliated "
        "First Lien Debt Aerospace & Defense "
        "Sky Merger Sub, LLC - Delayed Draw Term Loan "
        "Reference Rate and Spread S + 6.35% Interest Rate 10.04% "
        "Maturity Date 5/28/2029"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_msd_equity_leaf_preferred_stock():
    """Preferred equity with class designation is a leaf."""
    ident = (
        "Investments Investments - non-controlled/non-affiliated "
        "Preferred Equity Services: Consumer "
        "Metropolis Technologies Inc. - Class D Preferred Stock"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_msd_industry_subtotal_is_category_rollup():
    """Industry-level subtotal (type + industry, no issuer) is category rollup."""
    ident = (
        "Investments Investments - non-controlled/non-affiliated "
        "First Lien Debt Aerospace & Defense"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_disposition"] == "mixed_category_rollup"


@pytest.mark.parametrize(
    "asset_type",
    [
        "First Lien Debt Services: Consumer",
        "Second Lien Debt Services: Consumer",
        "Preferred Equity Services: Consumer",
    ],
)
def test_msd_services_consumer_subtotals_are_category_rollups(asset_type):
    """MSD service-consumer category rows are subtotals, not positions."""
    ident = (
        "Investments Investments - non-controlled/non-affiliated "
        f"{asset_type}"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_disposition"] == "mixed_category_rollup"


def test_msd_bare_type_subtotal_is_category_rollup():
    """Bare instrument type subtotal (no industry or issuer) is category rollup."""
    ident = (
        "Investments Investments - non-controlled/non-affiliated First Lien Debt"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_disposition"] == "mixed_category_rollup"


def test_msd_affiliation_subtotal_is_category_rollup():
    """Affiliation-only subtotal is category rollup."""
    ident = "Investments Investments - non-controlled/non-affiliated"
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_disposition"] == "mixed_category_rollup"


def test_msd_total_row_is_total_rollup():
    """Total Investments row is classified as total rollup."""
    ident = (
        "Investments Investments Total Investments "
        "- non-controlled/non-affiliated"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_disposition"] == "mixed_total_rollup"


def test_msd_total_preferred_equity_is_total_rollup():
    """Total Preferred Equity row is classified as total rollup."""
    ident = (
        "Investments Investments - non-controlled/non-affiliated "
        "Total Preferred Equity"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_disposition"] == "mixed_total_rollup"


def test_msd_cash_is_non_private():
    """Cash and Cash Equivalents is classified as non-private market."""
    result = classify_identifier(MSD_CIK, "Cash and Cash Equivalents")
    assert result["wrapper_disposition"] == "non_private_market"


def test_msd_portfolio_total_is_non_private():
    """Portfolio total row is classified as non-private market."""
    result = classify_identifier(
        MSD_CIK, "Portfolio Investments, Cash and Cash Equivalents"
    )
    assert result["wrapper_disposition"] == "non_private_market"


def test_msd_truncated_prefix_classified():
    """Truncated prefix variant (nvestments) is still classified."""
    ident = (
        "nvestments Investments - non-controlled/non-affiliated "
        "First Lien Debt Construction & Building"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_family"] == "mixed"
    assert "rollup" in result["wrapper_disposition"]


def test_msd_uppercase_variant_classified():
    """ALL-CAPS prefix variant is classified."""
    ident = (
        "INVESTMENTS INVESTMENTS - NON-CONTROLLED/NON-AFFILIATED "
        "SECOND LIEN DEBT SERVICESConsumer "
        "Southern Veterinary Partners L L C Reference Rate and Spread "
        "S + 7.85% Interest Rate Floor 1.00% Interest Rate 12.25% "
        "Maturity Date 10/5/2028"
    )
    result = classify_identifier(MSD_CIK, ident)
    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_msd_fx_forward_is_derivative():
    """Foreign Currency Forward Contracts are classified as derivative."""
    result = classify_identifier(
        MSD_CIK,
        "Foreign Currency Forward Contracts - Derivative Counterparty "
        "Macquarie Settlement Date July 31, 2025",
    )
    assert result["wrapper_family"] == "derivative"


# ---------------------------------------------------------------------------
# Stellus Private Credit BDC (CIK 0001901037) - flat format, fallback-only
# ---------------------------------------------------------------------------
STELLUS_CIK = "0001901037"


def test_stellus_debt_term_loan_leaf():
    """Standard term loan identifier is classified as debt leaf."""
    result = classify_identifier(
        STELLUS_CIK, "2X LLC, Term Loan"
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_stellus_debt_revolver_leaf():
    """Revolver is classified as debt leaf."""
    result = classify_identifier(
        STELLUS_CIK, "American Refrigeration, LLC, Revolving Credit Facility"
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_stellus_debt_delayed_draw_leaf():
    """Delayed draw term loan is classified as debt leaf."""
    result = classify_identifier(
        STELLUS_CIK, "Amika OpCo LLC, Delayed Draw Term Loan"
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_stellus_debt_term_a_loan_leaf():
    """Non-standard 'Term A Loan' is classified as debt leaf."""
    result = classify_identifier(
        STELLUS_CIK, "AdCellerant LLC, Term A Loan"
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_stellus_debt_unitranche_leaf():
    """Unitranche loan is classified as debt leaf."""
    result = classify_identifier(
        STELLUS_CIK, "Craftable Intermediate II Inc., Unitranche Term Loan"
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_stellus_equity_class_a_units_leaf():
    """Class A Units equity position is classified as equity leaf."""
    result = classify_identifier(
        STELLUS_CIK, "TriplePoint Holdco LLC, Class A Units"
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_stellus_equity_common_stock_leaf():
    """Common stock is classified as equity leaf."""
    result = classify_identifier(
        STELLUS_CIK, "Monitorus Holding Limited, Common Stock"
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_stellus_equity_partnership_interest_leaf():
    """Partnership interest is classified as equity leaf."""
    result = classify_identifier(
        STELLUS_CIK, "Rallyday Elder Care Co-Investors LP, Partnership Interests"
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_stellus_equity_preferred_leaf():
    """Preferred units are classified as equity leaf."""
    result = classify_identifier(
        STELLUS_CIK, "Sapphire Aggregator LLC, Preferred Units"
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_stellus_pbdc_spv_suffix_classified_as_debt_leaf():
    """Positions with (PBDC SPV) suffix are still classified as debt leaf."""
    result = classify_identifier(
        STELLUS_CIK, "2X LLC, Term Loan (PBDC SPV)"
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_stellus_pbdc_spv_equity_classified():
    """Equity with (PBDC SPV) suffix is still classified as equity leaf."""
    result = classify_identifier(
        STELLUS_CIK, "CF Arch Holdings LLC, Class A Units (PBDC SPV)"
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_stellus_ehi_dash_hierarchy_classified():
    """EHI Buyer edge case with dash-separated hierarchy classifies correctly."""
    result = classify_identifier(
        STELLUS_CIK, "EHI Buyer, Inc - EHI Group Holdings, L.P.- Equity"
    )
    assert result["wrapper_family"] == "equity"


def test_stellus_convertible_bond_classified_as_debt():
    """Convertible bonds classify as debt."""
    result = classify_identifier(
        STELLUS_CIK, "Sapphire Aggregator LLC, Convertible Bonds"
    )
    assert result["wrapper_family"] == "debt"


def test_stellus_registered_in_supported_ciks():
    """Stellus CIK is in the supported wrapper registry."""
    assert STELLUS_CIK in supported_wrapper_ciks()
