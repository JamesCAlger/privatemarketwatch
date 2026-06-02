import pandas as pd

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
