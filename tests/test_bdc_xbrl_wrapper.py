import pandas as pd
import pytest

from pipeline.bdc_xbrl_wrapper import (
    add_bdc_xbrl_wrapper_columns,
    classify_identifier,
    is_non_private_market_identifier,
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


def test_trinity_fallback_rollups_and_cash_are_classified():
    cash = classify_identifier(
        "0001786108",
        "Portfolio Company Cash and Cash Equivalents Other cash accounts",
    )
    investments = classify_identifier(
        "0001786108",
        "Portfolio Company Investment in Securities",
    )
    issuer_total = classify_identifier("0001786108", "Total Bestow, Inc.")
    subtotal = classify_identifier(
        "0001786108",
        "Sub-total: Digital Assets Technology and Services (2.1%)",
    )

    assert cash["wrapper_disposition"] == "non_private_market"
    assert investments["wrapper_disposition"] == "aggregate"
    assert issuer_total["wrapper_disposition"] == "debt_total_rollup"
    assert subtotal["wrapper_disposition"] == "debt_total_rollup"


def test_trinity_control_affiliate_and_truncated_prefix_rows_are_rollups():
    control = classify_identifier("0001786108", "Control Investments Edeniq, Inc.")
    affiliate = classify_identifier(
        "0001786108",
        "Affiliate Investments Senior Credit Corp 2022 LLC",
    )
    combined = classify_identifier(
        "0001786108",
        "Control and Affiliate Investments",
    )
    truncated = classify_identifier(
        "0001786108",
        "ortfolio Company Debt Securities- United States Real Estate Technology",
    )

    assert control["wrapper_disposition"] == "aggregate"
    assert affiliate["wrapper_disposition"] == "aggregate"
    assert combined["wrapper_disposition"] == "aggregate"
    assert truncated["wrapper_disposition"] == "debt_category_rollup"


def test_trinity_affiliate_investments_numbered_header_is_aggregate():
    row = classify_identifier("0001786108", "Affiliate Investments1")

    assert row["wrapper_disposition"] == "aggregate"


def test_trinity_equipment_financing_leaf_still_classified():
    row = classify_identifier(
        "0001786108",
        "Portfolio Company Debt Securities- United States Food and Agriculture "
        "Technologies Miyokos Kitchen Type of Investment Equipment Financing "
        "Investment Date February 5, 2021 MaturityDate September 1, 2023 "
        "InterestRateFixed interest rate 8.5%; EOT 9.0%",
    )

    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_position_key"]
    assert row["wrapper_structured_leaf_key"]


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
    assert "0002031750" in supported_wrapper_ciks()
    assert "0001825384" in supported_wrapper_ciks()
    assert "0001930679" in supported_wrapper_ciks()
    assert "0001975736" in supported_wrapper_ciks()
    assert "0001911066" in supported_wrapper_ciks()
    assert "0001899017" in supported_wrapper_ciks()
    assert "0002012139" in supported_wrapper_ciks()
    assert "0001772704" in supported_wrapper_ciks()
    assert "Portfolio Company Debt Securities" in supported_prefixes_for_cik("1786108")
    assert "Investment Debt Investments" in supported_prefixes_for_cik("0001920145")


def test_kkr_fs_income_trust_pipe_debt_leaf():
    row = classify_identifier(
        "0001930679",
        "Apex Service Partners LLC | Commercial & Professional Services 3",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "KKR_FS_INCOME_TRUST_DEBT_LEAF_V1"
    assert row["wrapper_position_key"]


def test_kkr_fs_income_trust_affiliated_equity_leaf_strips_prefix_from_key():
    row = classify_identifier(
        "0001930679",
        "Affiliated Issuer | KSC I Aircraft LP, ABF Equity",
    )

    assert row["wrapper_family"] == "equity"
    assert row["wrapper_disposition"] == "equity_position_leaf"
    assert row["wrapper_position_key"] == "ksc i aircraft lp abf equity"


def test_kkr_fs_income_trust_comma_debt_leaf():
    row = classify_identifier(
        "0001930679",
        "GreenSky Holdings LLC, Term Loan, Financial Services 1",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_position_key"]


def test_kkr_fs_income_trust_total_identifier_is_not_leaf():
    row = classify_identifier("0001930679", "Total Debt Investments")

    assert row["wrapper_disposition"] == "debt_total_rollup"


def test_kkr_fs_income_trust_select_pipe_debt_leaf():
    row = classify_identifier(
        "0001975736",
        "A-Lign Assurance LLC | Software & Services 1",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "KKR_FS_INCOME_TRUST_SELECT_DEBT_LEAF_V1"
    assert row["wrapper_position_key"]


def test_kkr_fs_income_trust_select_affiliated_equity_leaf_strips_prefix_from_key():
    row = classify_identifier(
        "0001975736",
        "Affiliated Issuer | KSC I Aircraft LP, ABF Equity",
    )

    assert row["wrapper_family"] == "equity"
    assert row["wrapper_disposition"] == "equity_position_leaf"
    assert row["wrapper_position_key"] == "ksc i aircraft lp abf equity"


def test_kkr_fs_income_trust_select_comma_debt_leaf():
    row = classify_identifier(
        "0001975736",
        "Carrier Fire Protection, Commercial & Professional Services 1",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_position_key"]


def test_kkr_fs_income_trust_select_total_identifier_is_not_leaf():
    row = classify_identifier("0001975736", "Total Debt Investments")

    assert row["wrapper_disposition"] == "debt_total_rollup"


def test_nuveen_churchill_pipe_debt_leaf():
    row = classify_identifier(
        "0001911066",
        "Apex Service Partners, LLC | First Lien Debt (Delayed Draw) 2",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "NUVEEN_CHURCHILL_PCIF_DEBT_LEAF_V1"
    assert row["wrapper_position_key"] == "apex service partners llc delayed draw 2"


def test_nuveen_churchill_comma_debt_leaf():
    row = classify_identifier(
        "0001911066",
        "CV Holdco, LLC (Class Valuation), Subordinated Debt 2",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_position_key"] == "cv holdco llc class valuation 2"


def test_nuveen_churchill_equity_leaf():
    row = classify_identifier(
        "0001911066",
        "ATL GSE Holdings, LP | Class A Common Units",
    )

    assert row["wrapper_family"] == "equity"
    assert row["wrapper_disposition"] == "equity_position_leaf"


def test_nuveen_churchill_cash_row_is_non_private():
    row = classify_identifier(
        "0001911066",
        "First American Government Obligations Fund - Class Z",
    )

    assert row["wrapper_family"] == "cash"
    assert row["wrapper_disposition"] == "non_private_market"


def test_nuveen_churchill_total_identifier_is_not_leaf():
    row = classify_identifier("0001911066", "Total Investments")

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_total_rollup"


def test_nuveen_churchill_bare_class_valuation_stays_unclassified():
    row = classify_identifier("0001911066", "Class Valuation")

    assert row["wrapper_family"] == ""
    assert row["wrapper_disposition"] == ""


def test_bain_private_credit_debt_leaf_strips_current_coupon_only():
    first = classify_identifier(
        "0001899017",
        "Aerospace & Defense ATS First Lien Senior Secured Loan SOFR Spread "
        "5.75% Interest Rate 9.42% Maturity Date 7/12/2029",
    )
    second = classify_identifier(
        "0001899017",
        "Aerospace & Defense ATS First Lien Senior Secured Loan SOFR Spread "
        "5.75% Interest Rate 9.65% Maturity Date 7/12/2029",
    )
    different_spread = classify_identifier(
        "0001899017",
        "Aerospace & Defense ATS First Lien Senior Secured Loan SOFR Spread "
        "6.00% Interest Rate 9.65% Maturity Date 7/12/2029",
    )

    assert first["wrapper_family"] == "debt"
    assert first["wrapper_disposition"] == "debt_position_leaf"
    assert first["wrapper_rule_id"] == "BAIN_PRIVATE_CREDIT_DEBT_LEAF_V1"
    assert first["wrapper_position_key"] == second["wrapper_position_key"]
    assert first["wrapper_position_key"] != different_spread["wrapper_position_key"]
    assert "5 75" in first["wrapper_position_key"]
    assert "9 42" not in first["wrapper_position_key"]
    assert "7 12 2029" in first["wrapper_position_key"]


def test_bain_private_credit_prefixed_debt_leaf_matches_unprefixed_key():
    prefixed = classify_identifier(
        "0001899017",
        "Non-Controlled/Non-Affiliate Investments Aerospace & Defense ATS "
        "First Lien Senior Secured Loan SOFR Spread 5.75% Interest Rate 9.42% "
        "Maturity Date 7/12/2029",
    )
    unprefixed = classify_identifier(
        "0001899017",
        "Aerospace & Defense ATS First Lien Senior Secured Loan SOFR Spread "
        "5.75% Interest Rate 9.42% Maturity Date 7/12/2029",
    )

    assert prefixed["wrapper_family"] == "debt"
    assert prefixed["wrapper_disposition"] == "debt_position_leaf"
    assert prefixed["wrapper_position_key"] == unprefixed["wrapper_position_key"]


def test_bain_private_credit_equity_leaf():
    row = classify_identifier(
        "0001899017",
        "Legacy Corporate Lending HoldCo, LLC Preferred Equity",
    )

    assert row["wrapper_family"] == "equity"
    assert row["wrapper_disposition"] == "equity_position_leaf"


def test_bain_private_credit_cash_row_is_non_private():
    row = classify_identifier(
        "0001899017",
        "Controlled Affiliate Investments Cash Equivalents Goldman Sachs "
        "Financial Square Government Fund",
    )

    assert row["wrapper_family"] == "cash"
    assert row["wrapper_disposition"] == "non_private_market"


def test_bain_private_credit_total_identifier_is_not_leaf():
    row = classify_identifier("0001899017", "Total Investments")

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_total_rollup"


def test_bain_private_credit_bare_industry_stays_unclassified():
    row = classify_identifier("0001899017", "Aerospace & Defense")

    assert row["wrapper_family"] == ""
    assert row["wrapper_disposition"] == ""


def test_fortress_private_lending_debt_leaf_strips_current_coupon_only():
    first = classify_identifier(
        "0002012139",
        "Investments Non-controlled, Non-affiliated Investments Debt Investments "
        "Capital Goods Albion Fortress Intermediate Holdings LLC Investment "
        "First Lien - Term Loan Reference Rate and Spread EURIBOR+575 "
        "Interest Rate 7.8% Maturity Date 7/31/2031",
    )
    second = classify_identifier(
        "0002012139",
        "Investments Non-controlled, Non-affiliated Investments Debt Investments "
        "Capital Goods Albion Fortress Intermediate Holdings LLC Investment "
        "First Lien - Term Loan Reference Rate and Spread EURIBOR+575 "
        "Interest Rate 8.1% Maturity Date 7/31/2031",
    )
    different_spread = classify_identifier(
        "0002012139",
        "Investments Non-controlled, Non-affiliated Investments Debt Investments "
        "Capital Goods Albion Fortress Intermediate Holdings LLC Investment "
        "First Lien - Term Loan Reference Rate and Spread EURIBOR+600 "
        "Interest Rate 8.1% Maturity Date 7/31/2031",
    )

    assert first["wrapper_family"] == "debt"
    assert first["wrapper_disposition"] == "debt_position_leaf"
    assert first["wrapper_rule_id"] == "FORTRESS_PRIVATE_LENDING_DEBT_LEAF_V1"
    assert first["wrapper_position_key"] == second["wrapper_position_key"]
    assert first["wrapper_position_key"] != different_spread["wrapper_position_key"]
    assert "euribor 575" in first["wrapper_position_key"]
    assert "7 8" not in first["wrapper_position_key"]
    assert "7 31 2031" in first["wrapper_position_key"]


def test_fortress_private_lending_tranche_terms_remain_distinct():
    term = classify_identifier(
        "0002012139",
        "Investments Non-controlled, Non-affiliated Investments Debt Investments "
        "Commercial & Professional Services FR Refuel, LLC Investment "
        "First Lien - Term Loan Reference Rate and Spread SOFR+486 "
        "Interest Rate 8.5% Maturity Date 11/8/2028",
    )
    delayed_draw = classify_identifier(
        "0002012139",
        "Investments Non-controlled, Non-affiliated Investments Debt Investments "
        "Commercial & Professional Services FR Refuel, LLC Investment "
        "First Lien - Delayed Draw Term Loan Reference Rate and Spread SOFR+475 "
        "Interest Rate 8.44% Maturity Date 11/8/2028",
    )

    assert term["wrapper_disposition"] == "debt_position_leaf"
    assert delayed_draw["wrapper_disposition"] == "debt_position_leaf"
    assert term["wrapper_position_key"] != delayed_draw["wrapper_position_key"]


def test_fortress_private_lending_investment_type_debt_leaf():
    row = classify_identifier(
        "0002012139",
        "Albion Fortress Intermediate Holdings LLC Investment Type "
        "First Lien - Term Loan",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_position_key"]


def test_fortress_private_lending_equity_and_warrant_leaves():
    warrant = classify_identifier(
        "0002012139",
        "Investments Non-controlled, non-affiliated investments Equity investments "
        "Food Products Amy's Kitchen, LLC Investment Warrants",
    )
    equity = classify_identifier(
        "0002012139",
        "Investments Non-controlled, Affiliated investments Debt investments "
        "Consumer Services Ducky's Opco, LLC Investment Class A Units",
    )

    assert warrant["wrapper_family"] == "warrant"
    assert warrant["wrapper_disposition"] == "warrant_position_leaf"
    assert equity["wrapper_family"] == "equity"
    assert equity["wrapper_disposition"] == "equity_position_leaf"


def test_fortress_private_lending_total_identifier_is_not_leaf():
    row = classify_identifier("0002012139", "Total Investments")

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_total_rollup"


def test_fortress_private_lending_bare_issuer_stays_unclassified():
    row = classify_identifier("0002012139", "Amy's Kitchen, LLC")

    assert row["wrapper_family"] == ""
    assert row["wrapper_disposition"] == ""


def test_stone_point_credit_classifies_comma_debt_leaf():
    row = classify_identifier(
        "0001825384",
        "Accordion Partners LLC, First Lien Term Loan, Due 11/17/2031",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "STONE_POINT_CREDIT_DEBT_LEAF_V1"
    assert row["wrapper_position_key"]


def test_stone_point_credit_classifies_equity_leaf():
    row = classify_identifier(
        "0001825384",
        "ACC Ultimate Holdings, L.P., Preferred Equity , Acquisition Date 12/9/2025",
    )

    assert row["wrapper_family"] == "equity"
    assert row["wrapper_disposition"] == "equity_position_leaf"
    assert row["wrapper_rule_id"] == "STONE_POINT_CREDIT_EQUITY_LEAF_V1"
    assert row["wrapper_position_key"]


def test_stone_point_credit_catches_malformed_debt_identifier():
    row = classify_identifier(
        "0001825384",
        "none_cnst_string_AmerilifeGroupLlcFirstLienDelayedDrawTermLoanDue8302024",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"


def test_stone_point_credit_bare_issuer_stays_unclassified():
    row = classify_identifier("0001825384", "RSC Topco, Inc.")

    assert row["wrapper_disposition"] == ""


def test_blackrock_private_credit_classifies_hierarchy_debt_leaf():
    row = classify_identifier(
        "0001902649",
        "Debt Investments Capital Markets Apex Group Treasury LLC Instrument "
        "First Lien Term Loan Ref SOFR(Q) Floor -% Spread 3.5% Total Coupon "
        "7.17% Maturity 2/20/2032",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "BLACKROCK_PRIVATE_CREDIT_DEBT_LEAF_V1"
    assert row["wrapper_position_key"]
    assert "total coupon" not in row["wrapper_position_key"]


def test_blackrock_private_credit_category_row_is_rollup():
    row = classify_identifier(
        "0001902649",
        "Debt Investments Real Estate Management and Development",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] in {"aggregate", "debt_category_rollup"}


def test_blackrock_private_credit_cash_and_total_rows_are_not_leaves():
    cash = classify_identifier(
        "0001902649",
        "Cash and Cash Equivalents - 11.8% of Net Assets",
    )
    total = classify_identifier(
        "0001902649",
        "Total Cash and Investments - 174.5% of Net Assets",
    )

    assert cash["wrapper_disposition"] == "non_private_market"
    assert total["wrapper_disposition"] == "non_private_market"


def test_blackrock_private_credit_investments_total_is_rollup():
    row = classify_identifier(
        "0001902649",
        "Investments - 167.9% of Net Assets",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] in {"aggregate", "mixed_category_rollup"}


def test_blackrock_private_credit_treasury_borrower_is_not_cash():
    row = classify_identifier(
        "0001902649",
        "Debt Investments Capital Markets Apex Group Treasury LLC Investment "
        "First Lien Term Loan Ref SOFR(Q) Spread 3.50% Total Coupon 7.39% "
        "Maturity Date 2/20/2032",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"


# ---------------------------------------------------------------------------
# AB Private Credit Investors Corp wrapper (CIK 0001634452)
# ---------------------------------------------------------------------------


AB_PRIVATE_CREDIT_INVESTORS_CIK = "0001634452"


def test_ab_private_credit_pipe_debt_leaf_classified():
    row = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Corporate Debt | 1st Lien/Senior Secured Debt | Fusion Holding "
        "Corp | Software & Tech Services | Term Loan | 11.59% (S + 6.25%; "
        "0.75% Floor)| 09/15/2029",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_position_key"]


def test_ab_private_credit_current_coupon_stripped_from_position_key():
    first = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "US Corporate Debt | 1st Lien/Senior Secured Debt | Fusion Holding Corp "
        "| Software & Tech Services | Term Loan | 10.54% (S + 6.25%; 0.75% "
        "Floor) | 9/14/2029",
    )
    second = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "US Corporate Debt | 1st Lien/Senior Secured Debt | Fusion Holding Corp "
        "| Software & Tech Services | Term Loan | 12.75% (S + 6.25%; 0.75% "
        "Floor) | 9/14/2029",
    )

    assert first["wrapper_position_key"] == second["wrapper_position_key"]

    separate_rate_fields = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Corporate Debt | 1st Lien/Senior Secured Debt | Fusion Holding "
        "Corp | Software & Tech Services | Term Loan | 11.59% | S + 6.25% | "
        "1.00% Floor | 9/14/2029",
    )
    parenthetical_rate_fields = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "US Corporate Debt | 1st Lien/Senior Secured Debt | Fusion Holding Corp "
        "| Software & Tech Services | Term Loan | 10.54% (S + 6.25%; 1.00% "
        "Floor) | 9/14/2029",
    )

    assert separate_rate_fields["wrapper_position_key"] == parenthetical_rate_fields["wrapper_position_key"]


def test_ab_private_credit_category_rows_are_not_leaves():
    debt_category = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "Canadian 1st Lien/Senior Secured Debt",
    )
    equity_category = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Common Stock - 1.52%",
    )

    assert debt_category["wrapper_disposition"] in {
        "aggregate",
        "debt_category_rollup",
    }
    assert equity_category["wrapper_disposition"] in {
        "aggregate",
        "mixed_category_rollup",
    }


def test_ab_private_credit_equity_fund_and_warrant_leaves_classified():
    equity = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Common Stock | Stripe, Inc. | Class B Common Stock | Software & "
        "Tech Services | 5/17/2021",
    )
    fund = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "Canadian Investment Companies | GHP SPV-2, L.P. | Units",
    )
    warrant = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "France Warrants | Content Square SAS | Indemnity Series F Shares "
        "Warrants | Software & Tech Services | 11/30/2023",
    )

    assert equity["wrapper_family"] == "equity"
    assert equity["wrapper_disposition"] == "equity_position_leaf"
    assert fund["wrapper_family"] == "fund"
    assert fund["wrapper_disposition"] == "fund_position_leaf"
    assert warrant["wrapper_family"] == "warrant"
    assert warrant["wrapper_disposition"] == "warrant_position_leaf"


def test_ab_private_credit_cash_and_balance_sheet_rows_are_not_private_leaves():
    cash = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "Cash Equivalents | Blackrock T Fund I | 4.22%",
    )
    liabilities = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "LIABILITIES IN EXCESS OF OTHER ASSETS - (177.17%)",
    )

    assert cash["wrapper_disposition"] == "non_private_market"
    assert liabilities["wrapper_disposition"] in {
        "aggregate",
        "mixed_category_rollup",
    }


def test_ab_private_credit_registered_in_supported_ciks():
    assert AB_PRIVATE_CREDIT_INVESTORS_CIK in supported_wrapper_ciks()


def test_new_mountain_guardian_iv_pipe_debt_leaf():
    row = classify_identifier("0001925531", "AAH Topco, LLC | First Lien - Undrawn 1")

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "NEW_MOUNTAIN_GUARDIAN_IV_DEBT_LEAF_V1"
    assert "undrawn 1" in row["wrapper_position_key"]


def test_new_mountain_guardian_iv_comma_debt_leaf_and_typo():
    row = classify_identifier("0001925531", "Kaseya Inc., First lien")
    typo = classify_identifier("0001925531", "More cowbell II LLC, Fist lien - Undrawn")
    first_drawn = classify_identifier("0001925531", "eResearchTechnology, Inc., First Drawn")

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert typo["wrapper_family"] == "debt"
    assert typo["wrapper_disposition"] == "debt_position_leaf"
    assert first_drawn["wrapper_family"] == "debt"
    assert first_drawn["wrapper_disposition"] == "debt_position_leaf"


def test_new_mountain_guardian_iv_equity_and_fund_rows():
    equity = classify_identifier("0001925531", "Panzura Holdings, LLC | Class A-2 common units")
    fund = classify_identifier(
        "0001925531",
        "Ivy Hill Middle Market Credit Fund, Ltd | Structured Finance Obligations",
    )

    assert equity["wrapper_family"] == "equity"
    assert equity["wrapper_disposition"] == "equity_position_leaf"
    assert fund["wrapper_family"] == "fund"
    assert fund["wrapper_disposition"] == "fund_position_leaf"


def test_new_mountain_guardian_iv_total_cash_and_bare_issuer_not_leaves():
    total = classify_identifier("0001925531", "Total Investments")
    cash = classify_identifier("0001925531", "Cash and Cash Equivalents")
    bare_issuer = classify_identifier("0001925531", "Bullhorn, Inc.")

    assert total["wrapper_disposition"] == "debt_total_rollup"
    assert cash["wrapper_disposition"] == "non_private_market"
    assert bare_issuer["wrapper_disposition"] == ""


def test_new_mountain_guardian_iv_preserves_position_tranche_labels():
    drawn = classify_identifier("0001925531", "Bullhorn, Inc. | First Lien - Drawn")
    undrawn = classify_identifier("0001925531", "Bullhorn, Inc. | First Lien - Undrawn 1")
    numbered = classify_identifier("0001925531", "Bullhorn, Inc. | First Lien 1")

    assert drawn["wrapper_position_key"] != undrawn["wrapper_position_key"]
    assert drawn["wrapper_position_key"] != numbered["wrapper_position_key"]
    assert undrawn["wrapper_position_key"] != numbered["wrapper_position_key"]


def test_blackstone_real_estate_credit_flat_numeric_leaf():
    row = classify_identifier("0002049733", "1100 Peachtree")
    tranche = classify_identifier("0002049733", "BMARK 2025-B41 JRR")

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "BLACKSTONE_REAL_ESTATE_CREDIT_INCOME_DEBT_LEAF_V1"
    assert tranche["wrapper_family"] == "debt"
    assert tranche["wrapper_disposition"] == "debt_position_leaf"


def test_blackstone_real_estate_credit_loan_and_portfolio_leaves():
    loan = classify_identifier("0002049733", "ECI Mezzanine variable rate loan")
    portfolio = classify_identifier("0002049733", "Azalea Multifamily Portfolio")

    assert loan["wrapper_family"] == "debt"
    assert loan["wrapper_disposition"] == "debt_position_leaf"
    assert portfolio["wrapper_family"] == "debt"
    assert portfolio["wrapper_disposition"] == "debt_position_leaf"


def test_blackstone_real_estate_credit_text_only_property_leaves():
    ardan = classify_identifier("0002049733", "Ardan")
    journal = classify_identifier("0002049733", "The Journal Phase I")

    assert ardan["wrapper_family"] == "debt"
    assert ardan["wrapper_disposition"] == "debt_position_leaf"
    assert journal["wrapper_family"] == "debt"
    assert journal["wrapper_disposition"] == "debt_position_leaf"


def test_blackstone_real_estate_credit_cash_and_total_not_leaves():
    cash = classify_identifier("0002049733", "Dreyfus Government Cash Management")
    total = classify_identifier("0002049733", "Total Investments - 123.4%")

    assert cash["wrapper_disposition"] == "non_private_market"
    assert total["wrapper_disposition"] == "debt_total_rollup"


def test_blackstone_real_estate_credit_unseen_bare_text_remains_reviewable():
    row = classify_identifier("0002049733", "Unseen Property Name")

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] != "debt_position_leaf"
    assert not row["wrapper_position_key"]


def test_aps_bdc_pipe_debt_leaf():
    row = classify_identifier("0002083477", "AI Titan Parent, Inc. | CHS BDC 2 LLC 1")
    spv = classify_identifier("0002083477", "Associations, Inc. | APS CW SPV LLC 6")

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "APS_BDC_DEBT_LEAF_V1"
    assert spv["wrapper_family"] == "debt"
    assert spv["wrapper_disposition"] == "debt_position_leaf"


def test_aps_bdc_preserves_spv_tranche_labels():
    first = classify_identifier("0002083477", "Truck-Lite Co, LLC | APS CW SPV LLC 1")
    second = classify_identifier("0002083477", "Truck-Lite Co, LLC | APS CW SPV LLC 2")
    chs = classify_identifier("0002083477", "Truck-Lite Co, LLC | CHS BDC 2 LLC 1")

    assert first["wrapper_position_key"] != second["wrapper_position_key"]
    assert first["wrapper_position_key"] != chs["wrapper_position_key"]
    assert second["wrapper_position_key"] != chs["wrapper_position_key"]


def test_aps_bdc_cash_total_and_bare_issuer_not_private_leaves():
    cash = classify_identifier("0002083477", "Cash and Cash Equivalents")
    total = classify_identifier("0002083477", "Total Investments - 100.0%")
    bare = classify_identifier("0002083477", "AI Titan Parent, Inc.")

    assert cash["wrapper_disposition"] == "non_private_market"
    assert total["wrapper_disposition"] == "debt_total_rollup"
    assert bare["wrapper_disposition"] == ""


def test_overland_advantage_debt_leaf_and_key_strip_variants():
    first = classify_identifier(
        "0001965934",
        "Investments Non-controlled/non-affiliated senior secured debt Debt investments "
        "Construction & Engineering Stark Tech Holdco, LLC First lien senior secured "
        "delayed draw term loan Interest Rate SOFR + 6.00% Maturity Date 5/13/2030",
    )
    second = classify_identifier(
        "0001965934",
        "Investments Non-controlled/non-affiliated debt Debt investments "
        "Construction & Engineering Stark Tech Holdco, LLC First lien senior secured "
        "delayed draw term loan Interest Rate SOFR + 6.00% Maturity Date 05/13/2030",
    )

    assert first["wrapper_family"] == "debt"
    assert first["wrapper_disposition"] == "debt_position_leaf"
    assert first["wrapper_rule_id"] == "OVERLAND_ADVANTAGE_DEBT_LEAF_V1"
    assert second["wrapper_disposition"] == "debt_position_leaf"
    assert first["wrapper_position_key"] == second["wrapper_position_key"]
    assert "stark tech holdco" in first["wrapper_position_key"]
    assert "delayed draw term loan" in first["wrapper_position_key"]


def test_overland_advantage_preserves_distinct_facilities():
    term = classify_identifier(
        "0001965934",
        "Investments Non-controlled/non-affiliated debt Debt investments "
        "Commercial Services & Supplies CI (MG) GROUP, LLC First lien senior secured "
        "term loan Interest Rate SOFR + 5.50% Maturity Date 3/27/2030",
    )
    delayed_draw = classify_identifier(
        "0001965934",
        "Investments Non-controlled/non-affiliated debt Debt investments "
        "Commercial Services & Supplies CI (MG) GROUP, LLC First lien senior secured "
        "delayed draw term loan Interest Rate SOFR + 5.50% Maturity Date 03/27/2030",
    )
    revolver = classify_identifier(
        "0001965934",
        "Investments Non-controlled/non-affiliated debt Debt investments "
        "Commercial Services & Supplies CI (MG) GROUP, LLC First lien senior secured "
        "revolving loan Interest Rate SOFR + 5.50% Maturity Date 03/27/2030",
    )

    assert term["wrapper_position_key"] != delayed_draw["wrapper_position_key"]
    assert term["wrapper_position_key"] != revolver["wrapper_position_key"]
    assert delayed_draw["wrapper_position_key"] != revolver["wrapper_position_key"]


def test_overland_advantage_second_lien_unsecured_and_truncated_prefix():
    second_lien = classify_identifier(
        "0001965934",
        "Investments Non-controlled/non-affiliated debt Debt investments Consumer Finance "
        "Maxitransfers Blocker Corp Second lien senior secured term loan Interest Rate "
        "SOFR + 7.00% Maturity Date 06/18/2030",
    )
    unsecured = classify_identifier(
        "0001965934",
        "Investments Non-controlled/non-affiliated debt Debt investments Consumer Staples "
        "Distribution & Retail Hand Family Companies Holdings, LLC Unsecured delayed draw "
        "term loan Interest Rate SOFR + 9.00% Maturity Date 11/29/2030 One",
    )
    truncated = classify_identifier(
        "0001965934",
        "nvestments Non-controlled/non-affiliated senior secured debt Debt investments "
        "Electronic Equipment Emrld Borrower LP First lien senior secured term loan "
        "Interest Rate SOFR + 2.50% Maturity Date 5/31/2030",
    )

    assert second_lien["wrapper_disposition"] == "debt_position_leaf"
    assert "second lien" in second_lien["wrapper_position_key"]
    assert unsecured["wrapper_disposition"] == "debt_position_leaf"
    assert unsecured["wrapper_position_key"].endswith("one")
    assert truncated["wrapper_disposition"] == "debt_position_leaf"


def test_overland_advantage_cash_total_and_category_rows_not_leaves():
    cash_total = classify_identifier("0001965934", "Investments and Cash Equivalents")
    fedfund = classify_identifier(
        "0001965934",
        "Cash Equivalents BlackRock Liquidity FedFund - Institutional - Interest Rate 4.28%",
    )
    treasury = classify_identifier("0001965934", "U.S. Treasury Bill")
    debt_total = classify_identifier("0001965934", "Debt Investments")
    category = classify_identifier(
        "0001965934",
        "Investments Non-controlled/non-affiliated senior secured debt Debt investments "
        "Construction Material",
    )

    assert cash_total["wrapper_disposition"] == "non_private_market"
    assert fedfund["wrapper_disposition"] == "non_private_market"
    assert treasury["wrapper_disposition"] == "non_private_market"
    assert debt_total["wrapper_disposition"] == "aggregate"
    assert not debt_total["wrapper_position_key"]
    assert category["wrapper_disposition"] == "aggregate"
    assert not category["wrapper_position_key"]


def test_vista_credit_strategic_lending_debt_leaf_and_key_strip_variants():
    first = classify_identifier(
        "0001919369",
        "Investments \u2013 non-controlled/non-affiliated First-Lien Debt Data & Analytics "
        "Azurite Intermediate Holdings, Inc. Reference Rate and Spread SOFR + 6.00% "
        "Interest Rate 10.33% Maturity Date 3/19/2031",
    )
    second = classify_identifier(
        "0001919369",
        "Investments \u2013 non-controlled/non-affiliated First-Lien Debt Data & Analytics "
        "Azurite Intermediate Holdings, Inc. Reference Rate and Spread SOFR + 6.50% "
        "Interest Rate 10.86% Maturity Date 3/19/2031",
    )

    assert first["wrapper_family"] == "debt"
    assert first["wrapper_disposition"] == "debt_position_leaf"
    assert first["wrapper_rule_id"] == "VISTA_CREDIT_STRATEGIC_LENDING_DEBT_LEAF_V1"
    assert second["wrapper_disposition"] == "debt_position_leaf"
    assert first["wrapper_position_key"] == second["wrapper_position_key"]
    assert "azurite intermediate holdings inc" in first["wrapper_position_key"]
    assert "interest rate" not in first["wrapper_position_key"]
    assert "sofr" not in first["wrapper_position_key"]
    assert "maturity date 3 19" in first["wrapper_position_key"]


def test_vista_credit_strategic_lending_preserves_maturity_distinct_debt_keys():
    first = classify_identifier(
        "0001919369",
        "Investments \u2013 non-controlled/non-affiliated First-Lien Debt Data & Analytics "
        "Azurite Intermediate Holdings, Inc. Reference Rate and Spread SOFR + 6.00% "
        "Interest Rate 10.33% Maturity Date 3/19/2031",
    )
    second = classify_identifier(
        "0001919369",
        "Investments \u2013 non-controlled/non-affiliated First-Lien Debt Data & Analytics "
        "Azurite Intermediate Holdings, Inc. Reference Rate and Spread SOFR + 6.00% "
        "Interest Rate 10.33% Maturity Date 3/19/2032",
    )

    assert first["wrapper_position_key"] != second["wrapper_position_key"]


def test_vista_credit_strategic_lending_equity_leaves():
    preferred = classify_identifier(
        "0001919369",
        "Investments Preferred Equity Transportation, Logistics & Supply Chain "
        "Metropolis Technologies, Inc. Interest Rate 16.00% Maturity Date 5/14/2036",
    )
    other = classify_identifier(
        "0001919369",
        "Investments Other Equity Financials HPC GPFS Arsenal Co-Invest (Cayman) LP "
        "Maturity Date 5/14/2036",
    )

    assert preferred["wrapper_family"] == "equity"
    assert preferred["wrapper_disposition"] == "equity_position_leaf"
    assert other["wrapper_family"] == "equity"
    assert other["wrapper_disposition"] == "equity_position_leaf"


def test_vista_credit_strategic_lending_totals_headers_cash_and_lists_not_leaves():
    debt_total = classify_identifier("0001919369", "Total First-Lien Debt")
    equity_total = classify_identifier("0001919369", "Total Other Equity")
    industry = classify_identifier("0001919369", "Transportation, Logistics & Supply Chain")
    cash_total = classify_identifier(
        "0001919369",
        "Total Investments, Cash and Cash Equivalents and Restricted Cash and Cash Equivalents",
    )
    bare = classify_identifier("0001919369", "ASG III, LLC")
    acronis = classify_identifier("0001919369", "Acronis International")
    sumup = classify_identifier("0001919369", "SumUp Holdings Midco S.\u00e0 r.l")
    mckissock = classify_identifier("0001919369", "McKissock Investment Holdings")
    issuer_list = classify_identifier(
        "0001919369",
        "Acronis International, ASG III, LLC and MRI Software, LLC",
    )

    assert debt_total["wrapper_disposition"] in {"aggregate", "debt_total_rollup"}
    assert not debt_total["wrapper_position_key"]
    assert equity_total["wrapper_disposition"] in {"aggregate", "equity_total_rollup"}
    assert not equity_total["wrapper_position_key"]
    assert industry["wrapper_disposition"] in {"aggregate", "debt_category_rollup"}
    assert not industry["wrapper_position_key"]
    assert cash_total["wrapper_disposition"] == "non_private_market"
    assert bare["wrapper_disposition"] == "debt_position_leaf"
    assert acronis["wrapper_disposition"] == "debt_position_leaf"
    assert sumup["wrapper_disposition"] == "debt_position_leaf"
    assert mckissock["wrapper_disposition"] == "debt_position_leaf"
    assert issuer_list["wrapper_disposition"] != "debt_position_leaf"


def test_agl_private_credit_debt_prefix_variants_share_key():
    plain = classify_identifier(
        "0002011498",
        "Investments Non-controlled/Non-affiliated investments AMI Buyer, Inc. "
        "First Lien Revolving Loan Industry Semiconductors & Semiconductor Equipment "
        "Reference Rate and Spread SOFR + 5.25% All In Rate 9.69% "
        "Acquisition Date 10/21/2024 Maturity Date 10/17/2031",
    )
    debt = classify_identifier(
        "0002011498",
        "Investments Non-controlled/Non-affiliated debt investments AMI Buyer, Inc. "
        "First Lien First Lien Revolving Loan Industry Semiconductors & Semiconductor Equipment "
        "Reference Rate and Spread SOFR + 5.25% All In Rate 9.04% "
        "Acquisition Date 10/21/2024 Maturity Date 10/17/2031",
    )

    assert plain["wrapper_family"] == "debt"
    assert plain["wrapper_disposition"] == "debt_position_leaf"
    assert plain["wrapper_rule_id"] == "AGL_PRIVATE_CREDIT_INCOME_DEBT_LEAF_V1"
    assert debt["wrapper_disposition"] == "debt_position_leaf"
    assert plain["wrapper_position_key"] == debt["wrapper_position_key"]
    assert plain["wrapper_position_key"] == "ami buyer inc revolving loan"


def test_agl_private_credit_preserves_facility_type_and_term_loan_number():
    delayed = classify_identifier(
        "0002011498",
        "Investments Industry Software MRI Software LLC First Lien Delayed Draw "
        "Term Loan Reference Rate and Spread SOFR + 4.50% Acquisition Date "
        "10/21/2024 Maturity Date 8/29/2031",
    )
    term_two = classify_identifier(
        "0002011498",
        "Investments Non-controlled/Non-affiliated Debt investments Industry Software "
        "MRI Software LLC First Lien Term Loan #2 Reference Rate and Spread SOFR + 4.50% "
        "All In Rate 8.20% Acquisition Date 10/21/2024 Maturity Date 8/29/2031",
    )
    revolver = classify_identifier(
        "0002011498",
        "Industry Software MRI Software LLC First Lien Revolving Loan Reference Rate "
        "and Spread SOFR + 4.50% Acquisition Date 10/21/2024 Maturity Date 8/29/2031",
    )

    assert delayed["wrapper_disposition"] == "debt_position_leaf"
    assert term_two["wrapper_disposition"] == "debt_position_leaf"
    assert revolver["wrapper_disposition"] == "debt_position_leaf"
    assert "delayed draw term loan" in delayed["wrapper_position_key"]
    assert "term loan 2" in term_two["wrapper_position_key"]
    assert "revolving loan" in revolver["wrapper_position_key"]
    assert len({
        delayed["wrapper_position_key"],
        term_two["wrapper_position_key"],
        revolver["wrapper_position_key"],
    }) == 3


def test_agl_private_credit_equity_and_investment_fund_leaves():
    firebird = classify_identifier(
        "0002011498",
        "Investments Non-controlled/Non-affiliated equity investments Industry "
        "Commercial Services & Supplies Firebird Co-Invest L.P. LP Interest "
        "Acquisition Date 1/29/2025",
    )
    epci = classify_identifier(
        "0002011498",
        "Investments Non-controlled/affiliated Equity investments Industry "
        "Investment Funds AGL EPCI I Acquisition Date 3/25/2026",
    )

    assert firebird["wrapper_family"] == "equity"
    assert firebird["wrapper_disposition"] == "equity_position_leaf"
    assert firebird["wrapper_position_key"] == "firebird co invest l p lp interest"
    assert epci["wrapper_family"] == "equity"
    assert epci["wrapper_disposition"] == "equity_position_leaf"
    assert epci["wrapper_position_key"] == "agl epci i"


def test_agl_private_credit_cash_and_total_rows_not_leaves():
    cash = classify_identifier(
        "0002011498",
        "Investments Goldman Sachs Financial Square Government Institutional Fund",
    )
    debt_total = classify_identifier("0002011498", "Debt securities")
    bare_debt = classify_identifier(
        "0002011498",
        "Investments Non-controlled/Non-affiliated debt investments",
    )
    equity_total = classify_identifier("0002011498", "Total equity investment")

    assert cash["wrapper_disposition"] == "non_private_market"
    assert debt_total["wrapper_disposition"] == "aggregate"
    assert not debt_total["wrapper_position_key"]
    assert bare_debt["wrapper_disposition"] == "aggregate"
    assert equity_total["wrapper_disposition"] == "debt_total_rollup"


def test_ares_core_infrastructure_classifies_senior_subordinated_leaf():
    row = classify_identifier(
        "0002031750",
        "Retained Vantage Data Centers Intermediate Holdco, L.P, "
        "Senior subordinated loans",
    )
    no_comma = classify_identifier(
        "0002031750",
        "Applied Systems, Inc. First lien senior secured loan",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert row["wrapper_rule_id"] == "ARES_CORE_INFRASTRUCTURE_DEBT_LEAF_V1"
    assert row["wrapper_position_key"]
    assert no_comma["wrapper_family"] == "debt"
    assert no_comma["wrapper_disposition"] == "debt_position_leaf"


def test_ares_core_infrastructure_demotes_bare_loan_categories():
    senior_subordinated = classify_identifier(
        "0002031750",
        "Senior subordinated loans",
    )
    first_lien = classify_identifier(
        "0002031750",
        "First lien senior secured loans",
    )

    assert senior_subordinated["wrapper_family"] == "debt"
    assert senior_subordinated["wrapper_disposition"] == "aggregate"
    assert first_lien["wrapper_family"] == "debt"
    assert first_lien["wrapper_disposition"] == "aggregate"


def test_ares_core_infrastructure_canonicalizes_legal_suffix_and_loan_plural():
    singular = classify_identifier(
        "0002031750",
        "BCP Renaissance Parent L.L.C, First lien senior secured loan",
    )
    plural = classify_identifier(
        "0002031750",
        "BCP Renaissance Parent LLC, First lien senior secured loans",
    )

    assert singular["wrapper_disposition"] == "debt_position_leaf"
    assert plural["wrapper_disposition"] == "debt_position_leaf"
    assert singular["wrapper_position_key"] == plural["wrapper_position_key"]


def test_ares_core_infrastructure_classifies_equity_and_cash_rows():
    equity = classify_identifier(
        "0002031750",
        "Aspen Renewables Equity Holdings LLC, Common equity",
    )
    cash = classify_identifier(
        "0002031750",
        "First American U.S. Treasury Sweep (Y Shares),  Money Market Fund",
    )

    assert equity["wrapper_family"] == "equity"
    assert equity["wrapper_disposition"] == "equity_position_leaf"
    assert cash["wrapper_family"] == "cash"
    assert cash["wrapper_disposition"] == "non_private_market"


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


FIDELITY_PRIVATE_CREDIT_CENTRAL_CIK = "0001899996"


def test_fidelity_central_classifies_hierarchical_debt_leaf():
    row = classify_identifier(
        FIDELITY_PRIVATE_CREDIT_CENTRAL_CIK,
        "Investments Investments -- non-controlled/ non-affiliated First Lien Debt "
        "Automotive Parts & Equipment Arrowhead Holdco Company Term Loan "
        "Reference Rate and Spread SOFR + 5.25% Interest Rate 10.75% "
        "Maturity Date 8/31/2028",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"
    assert row["wrapper_position_key"]


def test_fidelity_central_classifies_hierarchical_equity_leaf():
    row = classify_identifier(
        FIDELITY_PRIVATE_CREDIT_CENTRAL_CIK,
        "Investments -- non-controlled/ non-affiliate Equity Aerospace & Defense "
        "Hitco Parent LLC Type Class A Units",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"


def test_fidelity_central_category_and_total_rows_are_not_leaves():
    category = classify_identifier(
        FIDELITY_PRIVATE_CREDIT_CENTRAL_CIK,
        "Investments Investments -- non-controlled/ non-affiliated Equity "
        "Life Sciences Tools & Services",
    )
    total = classify_identifier(
        FIDELITY_PRIVATE_CREDIT_CENTRAL_CIK,
        "Investments Investments -- non-controlled/ non-affiliated Total First Lien Debt",
    )

    assert category["wrapper_disposition"] in {"aggregate", "mixed_category_rollup"}
    assert not category["wrapper_position_key"]
    assert total["wrapper_disposition"] in {"aggregate", "mixed_total_rollup"}
    assert not total["wrapper_position_key"]


def test_fidelity_central_money_market_rows_are_non_private():
    row = classify_identifier(
        FIDELITY_PRIVATE_CREDIT_CENTRAL_CIK,
        "Total Money Market Mutual Funds Fidelity Floating Rate Central Fund Mutual Fund",
    )

    assert row["wrapper_disposition"] == "non_private_market"


def test_fidelity_central_position_key_strips_rate_and_prefix_variants():
    first = classify_identifier(
        FIDELITY_PRIVATE_CREDIT_CENTRAL_CIK,
        "Investments Investments -- non-controlled/ non-affiliated First Lien Debt "
        "Automotive Parts & Equipment Arrowhead Holdco Company Term Loan "
        "Reference Rate and Spread SOFR + 5.25% Interest Rate 10.75% "
        "Maturity Date 8/31/2028",
    )
    second = classify_identifier(
        FIDELITY_PRIVATE_CREDIT_CENTRAL_CIK,
        "Investments -- non-controlled/ non-affiliate First Lien Debt "
        "Automotive Parts & Equipment Arrowhead Holdco Company Term Loan "
        "Reference Rate and Spread SOFR + 5.25% Interest Rate 9.70% "
        "Maturity Date 8/31/2028",
    )

    assert first["wrapper_position_key"] == second["wrapper_position_key"]


def test_fidelity_central_position_key_strips_affiliatd_typo_prefix():
    row = classify_identifier(
        FIDELITY_PRIVATE_CREDIT_CENTRAL_CIK,
        "Investments Investments -- non-controlled/ non-affiliatd First Lien Debt "
        "Application Software Routeware, Inc Delayed Draw Term Loan "
        "Maturity Date 9/18/2031",
    )

    assert row["wrapper_disposition"] == "mixed_position_leaf"
    assert "routeware inc" in row["wrapper_position_key"]
    assert "non affiliatd" not in row["wrapper_position_key"]


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
    assert row["wrapper_rule_id"] == "SARATOGA_MIXED_LEAF_V3"
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
    assert row["wrapper_rule_id"] == "SARATOGA_MIXED_AGGREGATE_V3"


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


def test_wrapper_does_not_treat_cash_slash_pik_coupon_as_cash():
    row = classify_identifier(
        "0001377936",
        "GoReact - Education Software - First Lien Term Loan "
        "(3M USD TERM SOFR+7.50%), 12.17% Cash/1.00% PIK, 1/17/2025",
    )

    assert row["wrapper_disposition"] == "mixed_position_leaf"


def test_saratoga_bare_non_profit_services_is_aggregate_header():
    row = classify_identifier("0001377936", "Non-profit Services")

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "aggregate"


def test_saratoga_wrapper_classifies_terminal_instrument_without_issuer_as_leaf():
    row = classify_identifier(
        "0001377936",
        "Non-control/Non-affiliate investments - 229.3% - Direct Selling Software - Common Units",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"
    assert row["wrapper_position_key"]


def test_saratoga_wrapper_classifies_no_prefix_syndicated_loan_leaf():
    row = classify_identifier(
        "0001377936",
        "DRW Holdings, LLC - Banking, Finance, Insurance & Real Estate - DRW Holdings LLC - Loan",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"
    assert row["wrapper_position_key"]


def test_saratoga_wrapper_classifies_no_prefix_loan_one_leaf():
    row = classify_identifier(
        "0001377936",
        "PHYSICIAN PARTNERS, LLC - Healthcare & Pharmaceuticals - Physician Partners LLC - Loan - One",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"


def test_saratoga_wrapper_classifies_compact_dash_loan_leaf():
    row = classify_identifier(
        "0001377936",
        "Isolved Inc.-Services: Business-Infinisource/iSolved 7/25 Cov-lite TL B - Loan",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"


def test_saratoga_wrapper_classifies_industry_issuer_loan_leaf():
    row = classify_identifier(
        "0001377936",
        "Healthcare & Pharmaceuticals - Pediatric Associates Holding Company LLC - Loan",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"


def test_saratoga_wrapper_classifies_compact_term_loan_leaf():
    row = classify_identifier(
        "0001377936",
        "Fiesta Purchaser, Inc-Beverage, Food & Tobacco Term-Loan B (12/24)-Loan",
    )

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "mixed_position_leaf"


def test_saratoga_wrapper_keeps_plain_industry_as_aggregate_after_no_prefix_loan_rule():
    row = classify_identifier("0001377936", "Banking, Finance, Insurance & Real Estate")

    assert row["wrapper_family"] == "mixed"
    assert row["wrapper_disposition"] == "aggregate"


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


# ---------------------------------------------------------------------------
# Goldman Sachs Private Middle Market Credit II (0001772704)
# ---------------------------------------------------------------------------


def test_gs_middle_market_ii_debt_key_strips_display_pct_and_current_coupon():
    first = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 152.1% United States - 147.5% "
        "1st Lien/Senior Secured Debt - 143.6% AQ Helios Buyer, Inc. "
        "(dba SurePoint) Software Interest Rate 10.93% Reference Rate and "
        "Spread S + 7.00% Maturity 12/31/26",
    )
    second = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 158.5% United States - 153.9% "
        "1st Lien/Senior Secured Debt - 149.8% AQ Helios Buyer, Inc. "
        "(dba SurePoint) Software Interest Rate 10.94% Reference Rate and "
        "Spread S + 7.00% Maturity 12/31/26",
    )
    changed_spread = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 158.5% United States - 153.9% "
        "1st Lien/Senior Secured Debt - 149.8% AQ Helios Buyer, Inc. "
        "(dba SurePoint) Software Interest Rate 11.94% Reference Rate and "
        "Spread S + 8.00% Maturity 12/31/26",
    )

    assert first["wrapper_family"] == "debt"
    assert first["wrapper_disposition"] == "debt_position_leaf"
    assert first["wrapper_rule_id"] == "GS_PRIVATE_MIDDLE_MARKET_II_DEBT_LEAF_V1"
    assert first["wrapper_position_key"] == second["wrapper_position_key"]
    assert first["wrapper_position_key"] != changed_spread["wrapper_position_key"]
    assert "152 1" not in first["wrapper_position_key"]
    assert "10 93" not in first["wrapper_position_key"]
    assert "s 7 00" in first["wrapper_position_key"]
    assert "12 31 26" in first["wrapper_position_key"]


def test_gs_middle_market_ii_truncated_prefix_classified():
    row = classify_identifier(
        "0001772704",
        "IInvestment Debt Investments - 158.5% United States - 153.9% "
        "1st Lien/Senior Secured Debt - 149.8% Eptam Plastics, Ltd. "
        "Industry Health Care Equipment & Supplies Interest Rate 9.32% "
        "Reference Rate and Spread S + 5.50% Maturity 12/06/27 Three",
    )

    assert row["wrapper_family"] == "debt"
    assert row["wrapper_disposition"] == "debt_position_leaf"
    assert "three" in row["wrapper_position_key"]


def test_gs_middle_market_ii_lot_suffixes_remain_distinct():
    base = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 152.1% United States - 147.5% "
        "1st Lien/Senior Secured Debt - 143.6% FS WhiteWater Borrower, LLC "
        "(fka Whitewater Holding Company LLC) Industry Diversified Consumer "
        "Services Interest Rate 9.10% Reference Rate and Spread S + 5.25% "
        "Maturity 12/21/29",
    )
    one = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 152.1% United States - 147.5% "
        "1st Lien/Senior Secured Debt - 143.6% FS WhiteWater Borrower, LLC "
        "(fka Whitewater Holding Company LLC) Industry Diversified Consumer "
        "Services Interest Rate 9.10% Reference Rate and Spread S + 5.25% "
        "Maturity 12/21/29 One",
    )

    assert base["wrapper_disposition"] == "debt_position_leaf"
    assert one["wrapper_disposition"] == "debt_position_leaf"
    assert base["wrapper_position_key"] != one["wrapper_position_key"]


def test_gs_middle_market_ii_debt_key_normalizes_rate_industry_and_year_width():
    older = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 204.80% United States - 197.87% "
        "1st Lien/Senior Secured Debt - 195.60% WorkForce Software, LLC "
        "Software Reference Rate and Spread L + 7.25% incl. 3.00% PIK "
        "Maturity 07/31/2025 Two",
    )
    newer = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 198.24% United States - 191.38% "
        "1st Lien/Senior Secured Debt - 188.72% WorkForce Software, LLC "
        "Industry Software Reference Rate and Spread L + 7.25% incl 3.00% PIK "
        "Maturity 07/31/25 Two",
    )

    assert older["wrapper_disposition"] == "debt_position_leaf"
    assert newer["wrapper_disposition"] == "debt_position_leaf"
    assert older["wrapper_structured_leaf_key"] == newer["wrapper_structured_leaf_key"]


def test_gs_middle_market_ii_debt_key_preserves_spread_terms_but_strips_current_coupon():
    cdn_with_spread = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 180.0% Canada - 3.2% "
        "1st Lien/Senior Secured Debt - 3.1% 1272775 B.C. LTD. "
        "(dba Everest Clinical Research) Industry Professional Services "
        "Reference Rate and Spread CDN P + 4.75% Maturity 11/06/2026",
    )
    cdn_without_spread = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 175.0% Canada - 3.0% "
        "1st Lien/Senior Secured Debt - 2.9% 1272775 B.C. LTD. "
        "(dba Everest Clinical Research) Industry Professional Services "
        "Maturity 11/06/26",
    )
    glued_interest = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 150.0% United States - 145.0% "
        "1st Lien/Senior Secured Debt - 2.0% Acquia Inc. Software"
        "Interest Rate12.16 Maturity 10/31/25",
    )
    missing_pik_label = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 198.24% United States - 191.38% "
        "1st Lien/Senior Secured Debt - 188.72% WorkForce Software, LLC "
        "Industry Software Reference Rate and Spread L + 7.25% incl 3.00 "
        "Maturity 07/31/25 Two",
    )

    assert cdn_with_spread["wrapper_position_key"] != cdn_without_spread["wrapper_position_key"]
    assert "cdn p 4 75" in cdn_with_spread["wrapper_position_key"]
    assert "interest rate12" not in glued_interest["wrapper_position_key"]
    assert "incl 3 00" in missing_pik_label["wrapper_position_key"]


def test_gs_middle_market_ii_equity_and_warrant_leaves():
    equity = classify_identifier(
        "0001772704",
        "Investment Equity Securities - 0.6% United States - 0.6% Common Stock "
        "- 0.6% Flexera Software LLC Industry Software",
    )
    warrant = classify_identifier("0001772704", "Warrants -0.04% Zep Inc.")

    assert equity["wrapper_family"] == "equity"
    assert equity["wrapper_disposition"] == "equity_position_leaf"
    assert warrant["wrapper_family"] == "warrant"
    assert warrant["wrapper_disposition"] == "warrant_position_leaf"


def test_gs_middle_market_ii_cash_and_totals_are_not_private_leaves():
    cash = classify_identifier(
        "0001772704",
        "Non-Controlled Affiliates Goldman Sachs Financial Square Government Fund",
    )
    total = classify_identifier(
        "0001772704",
        "Total Investments and Investments in Affiliated Money Market Fund - 197.7%",
    )
    country = classify_identifier("0001772704", "Total Canada")
    debt_bucket = classify_identifier(
        "0001772704",
        "Investment Debt Investments - 204.80% United States - 197.87% "
        "1st Lien/Senior Secured Debt - 195.60%",
    )
    equity_bucket = classify_identifier(
        "0001772704",
        "Equity Securities - 4.51%, United States - 4.51%, Common Stock - 1.06%",
    )

    assert cash["wrapper_disposition"] == "non_private_market"
    assert total["wrapper_disposition"] in {"debt_total_rollup", "non_private_market"}
    assert country["wrapper_disposition"] in {"aggregate", "debt_total_rollup"}
    assert debt_bucket["wrapper_disposition"] == "aggregate"
    assert equity_bucket["wrapper_disposition"] == "aggregate"
    assert debt_bucket["wrapper_signature_status"] == "pass"
    assert equity_bucket["wrapper_signature_status"] == "pass"


def test_gs_middle_market_ii_bare_affiliate_is_not_leaf():
    row = classify_identifier("0001772704", "Non-Controlled Affiliates Pluralsight, Inc.")

    assert row["wrapper_disposition"] != "debt_position_leaf"
    assert not row["wrapper_position_key"]


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


# ---------------------------------------------------------------------------
# Golub Capital Private Credit Fund (CIK 0001930087) - pipe/comma flat format
# ---------------------------------------------------------------------------
GOLUB_PRIVATE_CREDIT_CIK = "0001930087"


def test_golub_private_credit_pipe_one_stop_leaf():
    """Pipe-delimited one-stop loans classify as debt leaves."""
    result = classify_identifier(
        GOLUB_PRIVATE_CREDIT_CIK,
        "ABC Legal Holdings, LLC | One stop 1",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_golub_private_credit_one_stop_spacing_variant_leaf():
    """One-stop tranche labels without a space before the number classify."""
    result = classify_identifier(
        GOLUB_PRIVATE_CREDIT_CIK,
        "YI, LLC, One stop1",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_golub_private_credit_comma_senior_secured_leaf():
    """Comma-delimited senior secured loans classify across older quarters."""
    result = classify_identifier(
        GOLUB_PRIVATE_CREDIT_CIK,
        "AAL Delaware, Senior secured",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_golub_private_credit_structured_finance_note_leaf():
    """Structured finance notes classify as debt leaves."""
    result = classify_identifier(
        GOLUB_PRIVATE_CREDIT_CIK,
        "AGL CLO 20 Ltd. | Structured Finance Note",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_golub_private_credit_equity_leaf():
    """Common/preferred stock and LP/LLC interests classify as equity leaves."""
    common = classify_identifier(
        GOLUB_PRIVATE_CREDIT_CIK,
        "Action Termite Control, LLC | Common stock",
    )
    lp_interest = classify_identifier(
        GOLUB_PRIVATE_CREDIT_CIK,
        "Amberfield Acquisition Co. | LP interest 1",
    )
    assert common["wrapper_family"] == "equity"
    assert common["wrapper_disposition"] == "equity_position_leaf"
    assert lp_interest["wrapper_family"] == "equity"
    assert lp_interest["wrapper_disposition"] == "equity_position_leaf"


def test_golub_private_credit_warrant_leaf():
    """Warrant positions classify as warrant leaves."""
    result = classify_identifier(
        GOLUB_PRIVATE_CREDIT_CIK,
        "Example Holdings, Inc. | Warrant",
    )
    assert result["wrapper_family"] == "warrant"
    assert result["wrapper_disposition"] == "warrant_position_leaf"


def test_golub_private_credit_money_market_is_non_private():
    """Treasury money-market rows classify as non-private-market."""
    result = classify_identifier(
        GOLUB_PRIVATE_CREDIT_CIK,
        "Morgan Stanley Institutional Liquidity Funds - Treasury Portfolio "
        "Institutional Share Class (CUSIP 61747C582)",
    )
    assert result["wrapper_family"] == "cash"
    assert result["wrapper_disposition"] == "non_private_market"


def test_golub_private_credit_total_investments_is_aggregate():
    """Total investment labels are aggregates, not position leaves."""
    result = classify_identifier(GOLUB_PRIVATE_CREDIT_CIK, "Total Investments")
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_total_rollup"


def test_golub_private_credit_bare_issuer_not_forced_to_leaf():
    """Bare issuer names without instrument vocabulary remain unclassified."""
    result = classify_identifier(GOLUB_PRIVATE_CREDIT_CIK, "Bare Issuer Holdings LLC")
    assert result["wrapper_family"] == ""
    assert result["wrapper_disposition"] == ""


def test_golub_private_credit_registered_in_supported_ciks():
    """Golub Private Credit CIK is in the supported wrapper registry."""
    assert GOLUB_PRIVATE_CREDIT_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Golub Capital BDC 4 LLC (CIK 0001901612) - comma flat format
# ---------------------------------------------------------------------------
GOLUB_BDC4_CIK = "0001901612"


def test_golub_bdc4_comma_one_stop_leaf():
    """Comma-delimited one-stop loan rows classify as debt leaves."""
    result = classify_identifier(
        GOLUB_BDC4_CIK,
        "Avalara, Inc., One stop 1",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_golub_bdc4_senior_secured_leaf():
    """Comma-delimited senior-secured debt rows classify as debt leaves."""
    result = classify_identifier(
        GOLUB_BDC4_CIK,
        "DISA Holdings Corp., Senior secured 1",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_golub_bdc4_equity_leaf():
    """Common stock and LP unit rows classify as equity leaves."""
    common = classify_identifier(GOLUB_BDC4_CIK, "Critical Start, Inc., Common Stock")
    lp_units = classify_identifier(GOLUB_BDC4_CIK, "GTY Technology Holdings, Inc., LP units")

    assert common["wrapper_family"] == "equity"
    assert common["wrapper_disposition"] == "equity_position_leaf"
    assert lp_units["wrapper_family"] == "equity"
    assert lp_units["wrapper_disposition"] == "equity_position_leaf"


def test_golub_bdc4_cash_total_and_bare_issuer_are_not_leaves():
    """Cash totals and bare issuer rows are not forced into position leaves."""
    total = classify_identifier(GOLUB_BDC4_CIK, "Total Investments")
    cash = classify_identifier(GOLUB_BDC4_CIK, "Cash and Cash Equivalents")
    bare = classify_identifier(GOLUB_BDC4_CIK, "Avalara, Inc.")

    assert total["wrapper_disposition"] == "debt_total_rollup"
    assert cash["wrapper_disposition"] == "non_private_market"
    assert bare["wrapper_family"] == ""
    assert bare["wrapper_disposition"] == ""


def test_golub_bdc4_registered_in_supported_ciks():
    """Golub BDC 4 CIK is in the supported wrapper registry."""
    assert GOLUB_BDC4_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Oaktree Strategic Credit Fund (CIK 0001872371) - comma/pipe flat format
# ---------------------------------------------------------------------------
OAKTREE_STRATEGIC_CREDIT_CIK = "0001872371"


def test_oaktree_strategic_credit_first_lien_term_loan_leaf():
    """Comma-delimited first lien term loans classify as debt leaves."""
    result = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "Access CIG, LLC, First Lien Term Loan",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_oaktree_strategic_credit_html_delayed_draw_term_loan_leaf():
    """HTML-backed delayed draw term loan labels classify as debt leaves."""
    result = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "Mesoblast, Inc., First Lien Delayed Draw Term Loan",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_oaktree_strategic_credit_pipe_industry_debt_leaf():
    """Pipe-delimited issuer/industry/instrument rows classify by instrument."""
    result = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "Jonah Energy South Texas LLC | Oil & Gas Exploration & Production | "
        "First Lien Term Loan",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_oaktree_strategic_credit_subordinated_and_clo_debt_leaf():
    """Subordinated debt and CLO note labels classify as debt leaves."""
    subordinated = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "Recess Topco Partnership LP | Passenger Ground Transportation | "
        "Subordinated Debt Term Loan",
    )
    clo = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "Gallatin CLO X 2023-1, CLO Notes",
    )
    assert subordinated["wrapper_family"] == "debt"
    assert subordinated["wrapper_disposition"] == "debt_position_leaf"
    assert clo["wrapper_family"] == "debt"
    assert clo["wrapper_disposition"] == "debt_position_leaf"


def test_oaktree_strategic_credit_equity_leaf():
    """Common stock and preferred equity classify as equity leaves."""
    common = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "Delta Leasing SPV II LLC, Common Stock",
    )
    preferred = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "PetVet Care Centers, LLC, Preferred Equity",
    )
    assert common["wrapper_family"] == "equity"
    assert common["wrapper_disposition"] == "equity_position_leaf"
    assert preferred["wrapper_family"] == "equity"
    assert preferred["wrapper_disposition"] == "equity_position_leaf"


def test_oaktree_strategic_credit_warrant_leaf():
    """Warrant labels classify as warrant leaves."""
    result = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "ADC Therapeutics SA, Warrants",
    )
    assert result["wrapper_family"] == "warrant"
    assert result["wrapper_disposition"] == "warrant_position_leaf"


def test_oaktree_strategic_credit_treasury_fund_is_non_private():
    """Treasury fund cash-equivalent rows classify as non-private-market."""
    result = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "BNY Mellon U.S. Treasury Fund, Investor Shares",
    )
    assert result["wrapper_family"] == "cash"
    assert result["wrapper_disposition"] == "non_private_market"


def test_oaktree_strategic_credit_treasury_in_issuer_name_not_cash():
    """Treasury in an issuer name does not override an explicit loan label."""
    result = classify_identifier(
        OAKTREE_STRATEGIC_CREDIT_CIK,
        "Apex Group Treasury LLC, First Lien Term Loan",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_oaktree_strategic_credit_total_investments_is_rollup():
    """Total investment labels are rollups, not position leaves."""
    result = classify_identifier(OAKTREE_STRATEGIC_CREDIT_CIK, "Total Investments")
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_total_rollup"


def test_oaktree_strategic_credit_bare_issuer_not_forced_to_leaf():
    """Bare issuer names without instrument vocabulary remain unclassified."""
    result = classify_identifier(OAKTREE_STRATEGIC_CREDIT_CIK, "Bare Issuer LLC")
    assert result["wrapper_family"] == ""
    assert result["wrapper_disposition"] == ""


def test_oaktree_strategic_credit_registered_in_supported_ciks():
    """Oaktree Strategic Credit CIK is in the supported wrapper registry."""
    assert OAKTREE_STRATEGIC_CREDIT_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# North Haven Private Income Fund LLC (CIK 0001851322) - no-dash hierarchy
# ---------------------------------------------------------------------------
NORTH_HAVEN_PRIVATE_INCOME_CIK = "0001851322"


def test_north_haven_private_income_first_lien_debt_leaf():
    """No-dash first lien debt hierarchy rows classify as debt leaves."""
    result = classify_identifier(
        NORTH_HAVEN_PRIVATE_INCOME_CIK,
        "Investments-non-controlled/non-affiliated Debt Investments IT Services "
        "Apollo Acquisition, Inc. Investment First Lien Debt Reference Rate and "
        "Spread S + 5.00% Interest Rate 8.67% Maturity Date 12/30/2030",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_north_haven_private_income_second_lien_debt_leaf():
    """Second lien debt hierarchy rows classify as debt leaves."""
    result = classify_identifier(
        NORTH_HAVEN_PRIVATE_INCOME_CIK,
        "Investments-non-controlled/ non-affiliated Debt Investments IT Services "
        "Idera, Inc. Investment Second Lien Debt Reference Rate and Spread "
        "S + 6.75% Interest Rate 10.56% Maturity Date 03/02/2029",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_north_haven_private_income_common_and_preferred_equity_leaf():
    """Common and preferred equity hierarchy rows classify as equity leaves."""
    common = classify_identifier(
        NORTH_HAVEN_PRIVATE_INCOME_CIK,
        "Investments Commercial Services & Supplies Firebird Acquisition Corp, "
        "Inc. Investment Common Equity Acquisition Date 02/03/2025",
    )
    preferred = classify_identifier(
        NORTH_HAVEN_PRIVATE_INCOME_CIK,
        "Investments Containers & Packaging FORTIS Solutions Group, LLC "
        "Investment Preferred Equity Reference Rate and Spread 12.25% "
        "Acquisition Date 06/24/2022",
    )
    assert common["wrapper_family"] == "equity"
    assert common["wrapper_disposition"] == "equity_position_leaf"
    assert preferred["wrapper_family"] == "equity"
    assert preferred["wrapper_disposition"] == "equity_position_leaf"


def test_north_haven_private_income_llc_interest_leaf():
    """Affiliated fund LLC interests classify as equity leaves."""
    result = classify_identifier(
        NORTH_HAVEN_PRIVATE_INCOME_CIK,
        "Investments-controlled/affiliated Equity Investments Investment Fund "
        "North Haven Keystone, LLC Investment LLC Interest Acquisition Date "
        "10/29/2025",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_north_haven_private_income_numbered_headers_are_aggregate():
    """Investment One/Two/Three note labels are aggregate/header rows."""
    result = classify_identifier(NORTH_HAVEN_PRIVATE_INCOME_CIK, "Investment One")
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "aggregate"


def test_north_haven_private_income_unsecured_position_header_is_aggregate():
    """Numbered unsecured debt position headers are not debt leaves."""
    result = classify_identifier(
        NORTH_HAVEN_PRIVATE_INCOME_CIK, "One Unsecured Debt Position"
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "aggregate"


def test_north_haven_private_income_affiliated_issuer_total_is_aggregate():
    """Bare affiliated issuer total rows are aggregates, not equity leaves."""
    result = classify_identifier(
        NORTH_HAVEN_PRIVATE_INCOME_CIK,
        "Investments - non-controlled/affiliated KWOR Acquisition, Inc",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "aggregate"


def test_north_haven_private_income_money_market_is_non_private():
    """Money-market fund rows classify as non-private-market."""
    result = classify_identifier(
        NORTH_HAVEN_PRIVATE_INCOME_CIK,
        "Morgan Stanley Institutional Liquidity Government Fund Money Market",
    )
    assert result["wrapper_family"] == "cash"
    assert result["wrapper_disposition"] == "non_private_market"


def test_north_haven_private_income_old_bare_issuer_is_mixed_leaf():
    """Old issuer-only rows classify as mixed leaves, not debt/equity by text."""
    result = classify_identifier(NORTH_HAVEN_PRIVATE_INCOME_CIK, "Astra Acquisition Corp. 1")
    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_north_haven_private_income_short_label_without_entity_signal_unclassified():
    """Short labels without entity signals remain unclassified."""
    result = classify_identifier(NORTH_HAVEN_PRIVATE_INCOME_CIK, "DCA")
    assert result["wrapper_family"] == ""
    assert result["wrapper_disposition"] == ""


def test_north_haven_private_income_registered_in_supported_ciks():
    """North Haven Private Income CIK is in the supported wrapper registry."""
    assert NORTH_HAVEN_PRIVATE_INCOME_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Monroe Capital Income Plus Corp (CIK 0001742313)
# ---------------------------------------------------------------------------
MONROE_INCOME_PLUS_CIK = "0001742313"


def test_monroe_pipe_debt_leaf_classified():
    """Pipe-delimited Monroe debt rows classify as debt leaves."""
    result = classify_identifier(
        MONROE_INCOME_PLUS_CIK,
        "3C Buyer LLC (Revolver) | Senior Secured Loans",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_rule_id"] == "MONROE_INCOME_PLUS_DEBT_LEAF_V1"


def test_monroe_pipe_equity_leaf_classified():
    """Pipe-delimited Monroe equity rows classify as equity leaves."""
    result = classify_identifier(
        MONROE_INCOME_PLUS_CIK,
        "95 Percent Buyer, LLC (Class A units) | Equity Securities",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_monroe_legacy_comma_debt_leaf_classified():
    """Older comma-delimited family terms classify as debt leaves."""
    result = classify_identifier(
        MONROE_INCOME_PLUS_CIK,
        "Nastel Technologies, LLC, Senior Secured Loans (Revolver)",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_monroe_legacy_parenthetical_equity_leaf_classified():
    """Older parenthetical equity hints classify as equity leaves."""
    result = classify_identifier(
        MONROE_INCOME_PLUS_CIK,
        "ClearlyRated Capital, LLC (Class A units)",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_monroe_legacy_typo_series_units_equity_leaf_classified():
    """Typo variant 'Equity Securites, Series A units' remains an equity leaf."""
    result = classify_identifier(
        MONROE_INCOME_PLUS_CIK,
        "Really Great Reading Company, Inc., Equity Securites, Series A units",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_monroe_legacy_class_b_units_equity_leaf_classified():
    """Class B unit rows with share counts remain equity leaves."""
    result = classify_identifier(
        MONROE_INCOME_PLUS_CIK,
        "Forest Buyer, LLC ($1,088 Class B units)",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_monroe_sparse_issuer_only_row_is_mixed_leaf():
    """Sparse issuer-only rows remain position leaves without forced debt/equity family."""
    result = classify_identifier(MONROE_INCOME_PLUS_CIK, "Whistler Parent Holdings III, Inc.")
    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_monroe_total_investments_is_aggregate():
    """Portfolio totals are aggregates, not mixed leaves from entity signals."""
    result = classify_identifier(MONROE_INCOME_PLUS_CIK, "Total Investments")
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_total_rollup"


def test_monroe_short_label_without_entity_signal_unclassified():
    """Short labels without family terms or entity signals remain unclassified."""
    result = classify_identifier(MONROE_INCOME_PLUS_CIK, "NFS")
    assert result["wrapper_family"] == ""
    assert result["wrapper_disposition"] == ""


def test_monroe_registered_in_supported_ciks():
    """Monroe CIK is in the supported wrapper registry."""
    assert MONROE_INCOME_PLUS_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# HPS Corporate Lending Fund (CIK 0001838126) - bare issuer name format
# ---------------------------------------------------------------------------
HPS_CORPORATE_LENDING_CIK = "0001838126"


def test_hps_bare_debt_classified_as_debt():
    """Bare issuer name with no instrument keyword falls to catch-all debt."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK, "123Dentist Inc 1"
    )
    assert result["wrapper_family"] == "debt"


def test_hps_bare_debt_with_pipe_classified():
    """Bare issuer with pipe-delimited affiliation still classifies as debt."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "ABC Technologies Inc 1 | Non-Affiliated Issuer",
    )
    assert result["wrapper_family"] == "debt"


def test_hps_preferred_stock_classified_as_equity():
    """Preferred stock via dash separator classifies as equity."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "BCPE Virginia Holdco, Inc. - Preferred Stock | Non-Affiliated Issuer",
    )
    assert result["wrapper_family"] == "equity"


def test_hps_preferred_shares_classified_as_equity():
    """Preferred shares variant classifies as equity."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "CG Parent Intermediate Holdings, Inc. - Preferred Shares",
    )
    assert result["wrapper_family"] == "equity"


def test_hps_ordinary_shares_classified_as_equity():
    """Ordinary shares classifies as equity."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "AMR GP Holdings Ltd - Ordinary Shares | Non-Affiliated Issuer",
    )
    assert result["wrapper_family"] == "equity"


def test_hps_class_a_common_units_classified_as_equity():
    """Class A Common Units classifies as equity."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "Demon Holdco Lux Sarl - Class A Common Units | Affiliated Issuer",
    )
    assert result["wrapper_family"] == "equity"


def test_hps_llc_interest_classified_as_equity():
    """LLC Interest classifies as equity."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "SLF V AD1 Holdings, LLC - LLC Interest | Affiliated Issuer",
    )
    assert result["wrapper_family"] == "equity"


def test_hps_warrant_classified():
    """Warrants classify as warrant family."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "The ONE Group Hospitality, Inc. - B-2 Warrants | Non-Affiliated Issuer",
    )
    assert result["wrapper_family"] == "warrant"


def test_hps_clo_class_e_classified():
    """CLO tranche with Class E classifies as clo family."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "ABPCI Direct Lending Fund CLO XVII LLC - Class E | Non-Affiliated Issuer",
    )
    assert result["wrapper_family"] == "clo"


def test_hps_clo_subordinated_note_classified():
    """CLO subordinated note classifies as clo family."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "Dryden 108 CLO Ltd  - Subordinated Note | Non-Affiliated Issuer",
    )
    assert result["wrapper_family"] == "clo"


def test_hps_money_market_is_non_private():
    """J.P. Morgan money market fund is non-private-market."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "J.P. Morgan U.S. Government Fund, Institutional Shares | Affiliated Issuer",
    )
    assert result["wrapper_disposition"] == "non_private_market"


def test_hps_double_pipe_still_classifies():
    """Double pipe edge case still classifies correctly."""
    result = classify_identifier(
        HPS_CORPORATE_LENDING_CIK,
        "Club Car Wash Preferred, LLC - Preferred Stock 1 | | Non-Affiliated Issuer",
    )
    assert result["wrapper_family"] == "equity"


def test_hps_registered_in_supported_ciks():
    """HPS Corporate Lending CIK is in the supported wrapper registry."""
    assert HPS_CORPORATE_LENDING_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# HPS Corporate Capital Solutions Fund (CIK 0001989817)
# ---------------------------------------------------------------------------
HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK = "0001989817"


def test_hps_ccs_blocker_bare_issuer_classified_as_debt_leaf():
    result = classify_identifier(
        HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK,
        "International Construction Products, LLC",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_hps_ccs_pipe_affiliation_suffix_stripped_from_key():
    result = classify_identifier(
        HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK,
        "Equinox Holdings, Inc. 2 | Non-Affiliated Issuer",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"] == "equinox holdings inc 2"


def test_hps_ccs_trust_llp_and_rl_issuer_forms_are_debt_leaves():
    trust = classify_identifier(HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK, "Kowalski Trust")
    llp = classify_identifier(HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK, "Grant Thornton LLP")
    rl = classify_identifier(HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK, "Corza Medical S. R.L.")

    assert trust["wrapper_disposition"] == "debt_position_leaf"
    assert llp["wrapper_disposition"] == "debt_position_leaf"
    assert rl["wrapper_disposition"] == "debt_position_leaf"


def test_hps_ccs_equity_and_warrant_rows_classify_by_instrument_text():
    equity = classify_identifier(
        HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK,
        "Club Car Wash Preferred, LLC - Preferred Stock 1 | Non-Affiliated Issuer",
    )
    warrant = classify_identifier(
        HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK,
        "The ONE Group Hospitality, Inc. - Warrants 1",
    )

    assert equity["wrapper_family"] == "equity"
    assert equity["wrapper_disposition"] == "equity_position_leaf"
    assert warrant["wrapper_family"] == "warrant"
    assert warrant["wrapper_disposition"] == "warrant_position_leaf"


def test_hps_ccs_cash_fund_is_non_private_market():
    result = classify_identifier(
        HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK,
        "Dreyfus Government Cash Management | Non-Affiliated Issuer",
    )

    assert result["wrapper_family"] == "cash"
    assert result["wrapper_disposition"] == "non_private_market"


def test_hps_ccs_bare_affiliation_label_is_not_leaf():
    result = classify_identifier(
        HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK,
        "Non-Affiliated Issuer",
    )

    assert result["wrapper_family"] == ""
    assert result["wrapper_disposition"] == ""


def test_hps_ccs_registered_in_supported_ciks():
    assert HPS_CORPORATE_CAPITAL_SOLUTIONS_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Apollo Debt Solutions BDC (CIK 0001837532) - GICS sector + company + Investment Type
# ---------------------------------------------------------------------------
APOLLO_DS_CIK = "0001837532"


def test_apollo_ds_debt_term_loan_leaf():
    """Standard debt term loan with dash separator classifies as debt leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Aerospace & Defense MRO Holdings MRO Holdings, Inc. Investment Type "
        "First Lien Secured Debt - Term Loan Interest Rate S+450, 0.50% Floor "
        "Maturity Date 10/4/2032",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_apollo_ds_debt_revolver_leaf():
    """Revolver classifies as debt leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Insurance Howden Group HIG Finance 2 Limited Investment Type "
        "First Lien Secured Debt - Revolver Interest Rate S+275, 0.50% Floor "
        "Maturity Date 4/18/2030",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_apollo_ds_debt_delayed_draw_leaf():
    """Delayed draw classifies as debt leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Aerospace & Defense Triumph TITAN BW BORROWER L.P. Investment Type "
        "First Lien Secured Debt - Delayed Draw Interest Rate S+475, 0.50% "
        "Floor Maturity Date 07/24/2032",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_apollo_ds_debt_corporate_bond_leaf():
    """Corporate bonds classify as debt leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Diversified Telecommunication Services Uniti Group Inc. Windstream "
        "Services II, LLC First Lien Secured Debt - Corporate Bond Interest "
        "Rate 7.50% Maturity Date 10/15/2033",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_apollo_ds_equity_preferred_stocks_leaf():
    """Preferred equity classifies as equity leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Pharmaceuticals Avid Bioservices Space Parent, LP Investment Type "
        "Preferred Equity - Preferred Stocks",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_apollo_ds_equity_membership_interest_leaf():
    """Common equity membership interest classifies as equity leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Technology Hardware, Storage & Peripherals Valor VCI Intermediate "
        "Topco 2 LLC Common Equity - Membership Interest Equity Maturity Date "
        "12/31/1899",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_apollo_ds_equity_common_stock_leaf():
    """Common stock classifies as equity leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Hotels, Restaurants & Leisure Soho House & Co Inc. Soho House & Co "
        "Inc. Investment Type Common Equity - Stock",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_apollo_ds_investments_after_cash_is_aggregate():
    """Portfolio-level total is classified as aggregate."""
    result = classify_identifier(APOLLO_DS_CIK, "Investments after Cash Equivalents")
    disp = result.get("wrapper_disposition", "")
    assert "aggregate" in disp or "rollup" in disp or disp == "non_private_market"


def test_apollo_ds_investments_before_cash_is_aggregate():
    """Portfolio-level total is classified as aggregate."""
    result = classify_identifier(APOLLO_DS_CIK, "Investments before Cash Equivalents")
    disp = result.get("wrapper_disposition", "")
    assert "aggregate" in disp or "rollup" in disp or disp == "non_private_market"


def test_apollo_ds_sector_subtotal_is_not_leaf():
    """Bare GICS sector name is NOT classified as a leaf position."""
    result = classify_identifier(APOLLO_DS_CIK, "Software")
    assert result.get("wrapper_disposition", "") != "debt_position_leaf"
    assert result.get("wrapper_disposition", "") != "equity_position_leaf"


def test_apollo_ds_money_market_is_non_private():
    """Money market fund row classifies as non-private-market."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "State Street Institutional US Government Money Market Fund",
    )
    assert result.get("wrapper_disposition", "") == "non_private_market"


def test_apollo_ds_goldman_sachs_fund_is_non_private():
    """Goldman Sachs money market fund classifies as non-private-market."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Goldman Sachs Financial Square Government Fund Institutional",
    )
    assert result.get("wrapper_disposition", "") == "non_private_market"


def test_apollo_ds_pik_debt_leaf():
    """PIK-bearing debt position classifies as debt leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Professional Services Legends Legends Hospitality Holding Company, LLC "
        "Investment Type First Lien Secured Debt - Term Loan Interest Rate "
        "S+275 Cash plus 2.75% PIK, 0.75% Floor Maturity Date 8/22/2031",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_apollo_ds_en_dash_debt_leaf():
    """Identifier with en-dash (\u2013) separator classifies as debt leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Software Redwood Runway Bidco, LLC Investment Type First Lien "
        "Secured Debt \u2013 Term Loan Interest Rate S+500, 0.50% Floor "
        "Maturity Date 12/17/2031",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_apollo_ds_no_dash_debt_leaf():
    """No-dash debt identifier with Investment Type classifies as debt leaf."""
    result = classify_identifier(
        APOLLO_DS_CIK,
        "Commercial Services & Supplies BDO USA BDO USA, P.A. Investment Type "
        "First Lien Secured Debt Interest Rate S+600, 2.00% Floor Maturity "
        "Date 8/31/2028",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_apollo_ds_total_pharmaceuticals_is_aggregate():
    """'Total Pharmaceuticals' subtotal is classified as aggregate."""
    result = classify_identifier(APOLLO_DS_CIK, "Total Pharmaceuticals")
    disp = result.get("wrapper_disposition", "")
    assert "aggregate" in disp or "rollup" in disp


def test_apollo_ds_registered_in_supported_ciks():
    """Apollo Debt Solutions CIK is in the supported wrapper registry."""
    assert APOLLO_DS_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Apollo Origination II (L) Capital Trust (CIK 0002052152)
# ---------------------------------------------------------------------------
APOLLO_ORIGINATION_II_L_CIK = "0002052152"


def test_apollo_origination_ii_l_debt_delayed_draw_leaf():
    """Apollo Origination II delayed-draw debt rows classify as debt leaves."""
    result = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Automobile Components Clarience Technologies Truck-Lite Co., LLC "
        "Investment Type First Lien Secured Debt - Delayed Draw Interest Rate "
        "S+575, 0.75% Floor Maturity Date 2/13/2031",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_apollo_origination_ii_l_pik_debt_leaf():
    """PIK-bearing rate text remains a debt position, not cash/non-private."""
    result = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Life Sciences Tools & Services Curia Curia Global, Inc. "
        "Investment Type First Lien Secured Debt - Term Loan Interest Rate "
        "S+300 Cash plus 3.25% PIK Maturity Date 12/6/2029",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_apollo_origination_ii_l_convertible_bond_leaf():
    """Convertible bond rows classify as debt leaves."""
    result = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Media Gannett Gannett Co., Inc. Investment Type First Lien Secured "
        "Debt - Convertible Bond Interest Rate 6.00% Maturity Date 12/1/2031",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_apollo_origination_ii_l_preferred_equity_leaf():
    """Preferred equity rows classify as equity leaves."""
    result = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Insurance Higginbotham HIG Intermediate, Inc. Investment Type "
        "Preferred Equity - Cumulative Preferred Interest Rate Equity",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_apollo_origination_ii_l_sector_header_is_not_leaf():
    """Bare sector headers are rollups/aggregates, not position leaves."""
    result = classify_identifier(APOLLO_ORIGINATION_II_L_CIK, "Aerospace & Defense")
    assert result.get("wrapper_disposition", "") != "debt_position_leaf"
    assert result.get("wrapper_disposition", "") != "equity_position_leaf"


def test_apollo_origination_ii_l_issuer_rollup_is_not_leaf():
    """Issuer subtotal rows without Investment Type remain non-leaf rows."""
    result = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Commercial Services & Supplies AVI-SPL A&V Holdings Midco, LLC",
    )
    assert result.get("wrapper_family") == "debt"
    assert result.get("wrapper_disposition", "") == "aggregate"


def test_apollo_origination_ii_l_money_market_is_non_private():
    """Money market fund rows classify as non-private-market."""
    result = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Money Market Fund Goldman Sachs Financial Square Government Fund "
        "Institutional Shares",
    )
    assert result.get("wrapper_disposition", "") == "non_private_market"


def test_apollo_origination_ii_l_position_key_ignores_rate_drift():
    """Rate-only drift does not create a new wrapper position key."""
    first = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Commercial Services & Supplies Heritage Environmental Services "
        "Heritage Environmental Services, Inc. Investment Type First Lien "
        "Secured Debt - Term Loan Interest Rate S+500, 0.75% Floor "
        "Maturity Date 1/31/2031",
    )
    second = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Commercial Services & Supplies Heritage Environmental Services "
        "Heritage Environmental Services, Inc. Investment Type First Lien "
        "Secured Debt - Term Loan Interest Rate S+525, 0.75% Floor "
        "Maturity Date 1/31/2031",
    )
    assert first["wrapper_position_key"] == second["wrapper_position_key"]


def test_apollo_origination_ii_l_position_key_keeps_maturity_date():
    """Maturity date remains part of the position key after rate stripping."""
    first = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Commercial Services & Supplies Heritage Environmental Services "
        "Heritage Environmental Services, Inc. Investment Type First Lien "
        "Secured Debt - Term Loan Interest Rate S+500, 0.75% Floor "
        "Maturity Date 1/31/2031",
    )
    second = classify_identifier(
        APOLLO_ORIGINATION_II_L_CIK,
        "Commercial Services & Supplies Heritage Environmental Services "
        "Heritage Environmental Services, Inc. Investment Type First Lien "
        "Secured Debt - Term Loan Interest Rate S+500, 0.75% Floor "
        "Maturity Date 1/31/2032",
    )
    assert first["wrapper_position_key"] != second["wrapper_position_key"]


def test_apollo_origination_ii_l_registered_in_supported_ciks():
    assert APOLLO_ORIGINATION_II_L_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Blue Owl Technology Income Corp. (CIK 0001869453)
# ---------------------------------------------------------------------------
BLUE_OWL_TECH_INCOME_CIK = "0001869453"


def test_blue_owl_tech_pipe_debt_leaf_classified():
    """Pipe-delimited first lien senior secured loans classify as debt leaves."""
    result = classify_identifier(
        BLUE_OWL_TECH_INCOME_CIK,
        "AI Titan Parent, Inc. (dba Prometheus Group) | "
        "First lien senior secured delayed draw term loan",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_blue_owl_tech_comma_debt_leaf_classified():
    """Older comma-delimited debt identifiers classify as debt leaves."""
    result = classify_identifier(
        BLUE_OWL_TECH_INCOME_CIK,
        "Acrisure, LLC, Unsecured notes",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_blue_owl_tech_numbered_and_multi_currency_debt_leaf_classified():
    """Numbered loans and multi-currency revolvers classify as debt leaves."""
    numbered = classify_identifier(
        BLUE_OWL_TECH_INCOME_CIK,
        "Asurion, LLC, First lien senior secured loan4",
    )
    multi_currency = classify_identifier(
        BLUE_OWL_TECH_INCOME_CIK,
        "Jeppesen Holdings, LLC | First lien senior secured multi-currency revolving loan",
    )
    assert numbered["wrapper_family"] == "debt"
    assert numbered["wrapper_disposition"] == "debt_position_leaf"
    assert multi_currency["wrapper_family"] == "debt"
    assert multi_currency["wrapper_disposition"] == "debt_position_leaf"


def test_blue_owl_tech_equity_interest_leaf_classified():
    """LP and class-interest rows classify as equity leaves."""
    lp_interest = classify_identifier(
        BLUE_OWL_TECH_INCOME_CIK,
        "Elliott Alto Co-Investor Aggregator L.P., L.P. Interest",
    )
    class_interest = classify_identifier(
        BLUE_OWL_TECH_INCOME_CIK,
        "KWOL Acquisition, Inc. (dba Worldwide Clinical Trials) | Class A Interest",
    )
    assert lp_interest["wrapper_family"] == "equity"
    assert lp_interest["wrapper_disposition"] == "equity_position_leaf"
    assert class_interest["wrapper_family"] == "equity"
    assert class_interest["wrapper_disposition"] == "equity_position_leaf"


def test_blue_owl_tech_abf_section_header_is_aggregate():
    """ABF section headers are not position leaves."""
    result = classify_identifier(BLUE_OWL_TECH_INCOME_CIK, "ABF - Leasing")
    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "aggregate"


def test_blue_owl_tech_total_commitments_are_aggregate():
    """Commitment totals are aggregate diagnostics, not rollup blockers."""
    portfolio = classify_identifier(
        BLUE_OWL_TECH_INCOME_CIK,
        "Total Portfolio Company Commitments",
    )
    debt = classify_identifier(
        BLUE_OWL_TECH_INCOME_CIK,
        "Total non-controlled/non-affiliated - debt commitments",
    )
    assert portfolio["wrapper_family"] == "mixed"
    assert portfolio["wrapper_disposition"] == "aggregate"
    assert debt["wrapper_family"] == "mixed"
    assert debt["wrapper_disposition"] == "aggregate"


def test_blue_owl_tech_bare_name_without_instrument_stays_unclassified():
    """Bare specialty-finance names remain visible for residual review."""
    result = classify_identifier(BLUE_OWL_TECH_INCOME_CIK, "Blue Owl Credit SLF")
    assert result["wrapper_family"] == ""
    assert result["wrapper_disposition"] == ""


def test_blue_owl_tech_registered_in_supported_ciks():
    """Blue Owl Technology Income CIK is in the supported wrapper registry."""
    assert BLUE_OWL_TECH_INCOME_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# TPG Twin Brook Capital Income Fund (CIK 0001913724)
# ---------------------------------------------------------------------------
TPG_TWIN_BROOK_CIK = "0001913724"


def test_tpg_twin_brook_pipe_debt_leaf_classified():
    """Pipe-delimited first-lien senior secured loans classify as debt leaves."""
    result = classify_identifier(
        TPG_TWIN_BROOK_CIK,
        "AFC-Dell Holding Corp | First lien senior secured delayed draw term loan 1",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_tpg_twin_brook_comma_debt_leaf_classified():
    """Older comma-delimited first-lien identifiers classify as debt leaves."""
    result = classify_identifier(
        TPG_TWIN_BROOK_CIK,
        "AFC-Dell Holding Corp, First lien senior secured revolving loan 2",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_tpg_twin_brook_sponsor_subordinated_note_leaf_classified():
    """Sponsor subordinated notes classify as debt leaves."""
    result = classify_identifier(
        TPG_TWIN_BROOK_CIK,
        "Cosmetic Solutions LLC | Sponsor subordinated note",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_tpg_twin_brook_bare_equity_holding_leaf_classified():
    """Bare Twin Brook Equity Holdings rows classify as equity leaves."""
    result = classify_identifier(TPG_TWIN_BROOK_CIK, "Twin Brook Equity Holdings, LLC")
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_tpg_twin_brook_explicit_equity_interest_leaf_classified():
    """Explicit equity-interest variants classify as equity leaves."""
    result = classify_identifier(
        TPG_TWIN_BROOK_CIK,
        "Twin Brook Segregated Equity Holdings, LLC | Equity interest",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_tpg_twin_brook_total_investments_is_not_leaf():
    """Portfolio total rows are not position leaves."""
    result = classify_identifier(TPG_TWIN_BROOK_CIK, "Total Investments")
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_total_rollup"


def test_tpg_twin_brook_known_duplicate_issuer_debt_leaf_classified():
    """Known 2023-06 duplicate issuer-only debt rows classify narrowly."""
    result = classify_identifier(
        TPG_TWIN_BROOK_CIK,
        "NEFCO Holding Company, LLC, NEFCO Holding Company, LLC 1",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_tpg_twin_brook_registered_in_supported_ciks():
    """TPG Twin Brook CIK is in the supported wrapper registry."""
    assert TPG_TWIN_BROOK_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Stepstone Private Credit Fund LLC (CIK 0001950803)
# ---------------------------------------------------------------------------
STEPSTONE_PRIVATE_CREDIT_CIK = "0001950803"


def test_stepstone_pipe_debt_leaf_classified():
    """Pipe-delimited Stepstone loan rows classify as debt leaves."""
    identifier = (
        "Non-Controlled, Non-Affiliated Debt Investments | First Lien Senior Secured | "
        "Advertising | Finn Partners, Inc. Initial Term Loan | Reference Rate Spread / "
        "Floor | 3M SOFR + 6.50% / 1.00% | Cash Interest Rate / PIK Rate | "
        "10.32% | Maturity Date | 7/1/2026"
    )
    result = classify_identifier(
        STEPSTONE_PRIVATE_CREDIT_CIK,
        identifier,
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]
    assert not is_non_private_market_identifier(identifier)


def test_stepstone_cash_pay_term_loan_not_non_private():
    """Cash-pay loan descriptions are positions, not cash equivalents."""
    identifier = (
        "Non-Controlled, Non-Affiliated Debt Investments | First Lien Senior Secured | "
        "Life & Health Insurance | Pareto Health Intermediate Holdings Inc. "
        "A-1 Cash Pay Term Loan | 3M SOFR + 4.75% / 1.00% | 9.05% | 6/1/2030"
    )

    result = classify_identifier(STEPSTONE_PRIVATE_CREDIT_CIK, identifier)

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert not is_non_private_market_identifier(identifier)


def test_stepstone_total_first_lien_is_not_leaf():
    """Stepstone first-lien subtotals remain aggregate diagnostics."""
    identifiers = [
        "Non-Controlled, Non-Affiliated Debt Investments | First Lien Senior Secured | "
        "Total First Lien Senior Secured",
        "Non-Controlled Non-Affiliated Debt Investments | First Lien Senior Secured "
        "(continued) | Industrial Machinery (continued) |Total",
    ]

    for identifier in identifiers:
        result = classify_identifier(STEPSTONE_PRIVATE_CREDIT_CIK, identifier)
        assert result["wrapper_family"] == "debt"
        assert result["wrapper_disposition"] in {"aggregate", "debt_total_rollup"}


def test_stepstone_private_fund_total_is_not_leaf():
    """Fund section totals are not classified as LP-interest positions."""
    result = classify_identifier(
        STEPSTONE_PRIVATE_CREDIT_CIK,
        "Non-Controlled, Non-Affiliated Private Credit Funds | "
        "Limited Partnership Interests | Total Investments",
    )

    assert result["wrapper_family"] == "fund"
    assert result["wrapper_disposition"] in {"aggregate", "fund_total_rollup"}


def test_stepstone_bare_total_investments_is_aggregate():
    """Bare portfolio totals are aggregates, not missing loan positions."""
    bare = classify_identifier(STEPSTONE_PRIVATE_CREDIT_CIK, "Total Investments")
    cash_total = classify_identifier(
        STEPSTONE_PRIVATE_CREDIT_CIK,
        "Total Investments and Cash and Cash Equivalents and Restricted Cash "
        "and Restricted Cash Equivalents | One",
    )

    assert bare["wrapper_family"] == "debt"
    assert bare["wrapper_disposition"] == "aggregate"
    assert cash_total["wrapper_family"] == "debt"
    assert cash_total["wrapper_disposition"] == "non_private_market"


def test_stepstone_cash_row_is_non_private():
    """Cash and restricted-cash rows stay out of private-market positions."""
    result = classify_identifier(
        STEPSTONE_PRIVATE_CREDIT_CIK,
        "Cash and Cash Equivalents and Restricted Cash and Restricted Cash "
        "Equivalents | Other cash accounts | One",
    )

    assert result["wrapper_disposition"] == "non_private_market"


def test_stepstone_quoted_identifier_classified():
    """Quoted 2026 identifier variants still classify as debt leaves."""
    result = classify_identifier(
        STEPSTONE_PRIVATE_CREDIT_CIK,
        "\"Non-Controlled, Non-Affiliated Debt Investments | First Lien Senior "
        "Secured | Industrial Machinery | Rapid Pump Acquisition, Inc. Delayed "
        "Draw Term C Loan | Reference Rate Spread / Floor | 1M SOFR + 5.75% / "
        "1.00% | Cash Interest Rate / PIK Rate | 9.52% | Maturity Date | "
        "8/4/2027\"",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_stepstone_registered_in_supported_ciks():
    """Stepstone Private Credit CIK is in the supported wrapper registry."""
    assert STEPSTONE_PRIVATE_CREDIT_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Barings Private Credit Corp (CIK 0001859919)
# ---------------------------------------------------------------------------
BARINGS_PRIVATE_CREDIT_CIK = "0001859919"


def test_barings_pipe_debt_leaf_classified():
    """Pipe-delimited Barings loan rows classify as debt leaves."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "A.T. Holdings II LTD | First Lien Senior Secured Term Loan",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_barings_legacy_comma_debt_leaf_classified():
    """Legacy comma-delimited issuer, industry, instrument rows classify as debt leaves."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "Classic Collision (Summit Buyer, LLC), Auto Collision Repair Centers, "
        "First Lien Senior Secured Term Loan",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_barings_equity_units_leaf_classified():
    """LLC-unit rows classify as equity leaves."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "Eclipse Business Capital, LLC | LLC units",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_barings_member_interest_leaf_classified():
    """Member-interest rows classify as equity leaves."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "Thompson Rivers LLC,  Member Interest",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_barings_structured_notes_leaf_classified():
    """Subordinated structured note rows classify as debt leaves."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "CNSL 2025-1A | Subordinated Structured Notes",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_barings_municipal_revenue_bond_leaf_classified():
    """Municipal revenue bond rows classify as debt leaves."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "Bridger Aerospace Group Holdings, LLC, Environmental Industries, Municipal Revenue Bond",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_barings_investment_fund_leaf_classified():
    """Investment Funds & Vehicles rows classify as fund leaves."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "Waccamaw River LLC, Investment Funds & Vehicles",
    )
    assert result["wrapper_family"] == "fund"
    assert result["wrapper_disposition"] == "fund_position_leaf"


def test_barings_royalty_rights_leaf_classified():
    """Royalty-right rows classify as other private-market leaves."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "Coherus Biosciences, Inc. | Royalty Rights",
    )
    assert result["wrapper_family"] == "other"
    assert result["wrapper_disposition"] == "other_position_leaf"


def test_barings_exact_recurring_rocade_row_classified():
    """Exact recurring Rocade issuer-only rows classify without broad issuer matching."""
    result = classify_identifier(BARINGS_PRIVATE_CREDIT_CIK, "Rocade Holdings LLC")
    assert result["wrapper_family"] == "other"
    assert result["wrapper_disposition"] == "other_position_leaf"


def test_barings_warrant_leaf_classified():
    """Warrant rows classify separately from common equity."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "Policy Services Company, LLC, Property & Casualty Insurance, Warrants",
    )
    assert result["wrapper_family"] == "warrant"
    assert result["wrapper_disposition"] == "warrant_position_leaf"


def test_barings_total_investments_is_not_leaf():
    """Portfolio total rows are rollups, not position leaves."""
    result = classify_identifier(BARINGS_PRIVATE_CREDIT_CIK, "Total Investments")
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_total_rollup"


def test_barings_cash_row_is_non_private():
    """Cash and money market identifiers stay out of private-market positions."""
    result = classify_identifier(
        BARINGS_PRIVATE_CREDIT_CIK,
        "Cash and Cash Equivalents",
    )
    assert result["wrapper_disposition"] == "non_private_market"


def test_barings_uninstrumented_issuer_stays_unclassified():
    """Issuer-only rows remain visible instead of being broad-matched."""
    result = classify_identifier(BARINGS_PRIVATE_CREDIT_CIK, "Eclipse Business Capital Holdings LLC")
    assert result["wrapper_family"] == ""
    assert result["wrapper_disposition"] == ""


def test_barings_registered_in_supported_ciks():
    """Barings Private Credit CIK is in the supported wrapper registry."""
    assert BARINGS_PRIVATE_CREDIT_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# MidCap Financial Investment Corp (CIK 0001278752)
# ---------------------------------------------------------------------------
MIDCAP_FINANCIAL_INVESTMENT_CIK = "0001278752"


def test_midcap_total_investments_before_cash_is_aggregate():
    """Portfolio-level before-cash total is not a private-market position."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "Total Investments before Cash Equivalents",
    )
    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "non_private_market"


def test_midcap_non_controlled_hierarchy_row_is_aggregate():
    """Old affiliation/industry/instrument hierarchy rows are rollups."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "Non-Controlled/Non-Affiliated Investments, Healthcare & Pharmaceuticals, First Lien - Secured Debt",
    )
    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "aggregate"


def test_midcap_controlled_hierarchy_row_is_aggregate():
    """Controlled-investments hierarchy rows do not become position leaves."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "Controlled Investments, High Tech Industries, First Lien - Secured Debt",
    )
    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "aggregate"


def test_midcap_instrument_only_debt_row_is_aggregate():
    """Instrument-only debt subtotals lack issuer-level identity."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "First Lien - Secured Debt",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "aggregate"


def test_midcap_modern_debt_leaf_classified():
    """Modern flat rows with borrower, instrument, rate, and maturity classify as debt leaves."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "Biotechnology Rigel Pharmaceuticals Rigel Pharmaceuticals, Inc. "
        "First Lien Secured Debt - Term Loan SOFR+650, 4.00% Floor "
        "Maturity Date 09/01/27",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_midcap_g_treasury_borrower_is_private_credit_leaf():
    """Borrower names containing Treasury must not be treated as government cash equivalents."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "High Tech Industries Gtreasury G Treasury SS LLC First Lien Secured Debt "
        "SOFR+600, 1.00% Floor Maturity Date 06/29/29",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_midcap_modern_equity_leaf_classified():
    """Modern explicit common-equity rows classify as equity leaves."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "1244311 B.C. Ltd. | Common Equity - Common Stock",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_midcap_affiliated_membership_interest_leaf_classified():
    """Affiliated investment rows with explicit membership interests classify as equity."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "Affiliated Investments Auto Pool 2023 Trust (Del. Stat. Trust) ,Membership Interests",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_midcap_industry_issuer_without_instrument_stays_unclassified():
    """Bare industry-plus-issuer rows need source review before classification."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "Healthcare & Pharmaceuticals Celerion Celerion Buyer, Inc.",
    )
    assert result["wrapper_family"] == ""
    assert result["wrapper_disposition"] == ""


def test_midcap_structured_products_category_is_aggregate():
    """Structured Products and Other is a category row, not a leaf."""
    result = classify_identifier(
        MIDCAP_FINANCIAL_INVESTMENT_CIK,
        "Structured Products and Other",
    )
    assert result["wrapper_family"] == "other"
    assert result["wrapper_disposition"] == "aggregate"


def test_midcap_registered_in_supported_ciks():
    """MidCap Financial Investment CIK is in the supported wrapper registry."""
    assert MIDCAP_FINANCIAL_INVESTMENT_CIK in supported_wrapper_ciks()


def test_audax_hierarchy_debt_leaf_classified():
    """Audax hierarchy rows with Investment Type classify as debt leaves."""
    result = classify_identifier(
        "0001633858",
        "Portfolio Investments BANK LOANS: NON-CONTROL/NON-AFFILIATE INVESTMENTS - "
        "(94.3%) Healthcare & Pharmaceuticals AccentCare Investment Type Senior "
        "Secured Tranche A Term Loan Index S+ Spread 5.50% Interest Rate 9.81% "
        "Acquisition Date 2/5/2024 Maturity Date 6/20/2028",
    )
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]
    assert "interest rate" not in result["wrapper_position_key"]


def test_audax_hierarchy_equity_leaf_classified():
    """Audax hierarchy equity rows with Investment Type classify as equity leaves."""
    result = classify_identifier(
        "0001633858",
        "Portfolio Investments EQUITY AND PREFERRED SHARES: NON-CONTROL/NON-AFFILIATE "
        "INVESTMENTS- (1.5%) Services: Business Heartland Investment Type Co-Invest "
        "Units Acquisition Date 12/12/2023",
    )
    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_audax_industry_header_is_aggregate():
    """Audax industry headers without Investment Type are aggregates, not leaves."""
    truncated = classify_identifier(
        "0001633858",
        "ortfolio Investments BANK LOANS: NON-CONTROL/NON-AFFILIATE INVESTMENTS "
        "Construction & Building",
    )
    normal = classify_identifier(
        "0001633858",
        "Portfolio Investments EQUITY AND PREFERRED SHARES: NON-CONTROL/NON-AFFILIATE "
        "INVESTMENTS- (1.6%) Wholesale",
    )
    assert truncated["wrapper_family"] == "debt"
    assert truncated["wrapper_disposition"] in {"aggregate", "debt_category_rollup"}
    assert normal["wrapper_family"] == "equity"
    assert normal["wrapper_disposition"] in {"aggregate", "equity_category_rollup"}


def test_audax_total_portfolio_investments_is_aggregate():
    """Audax total portfolio rows are source aggregates."""
    result = classify_identifier("0001633858", "Total Portfolio Investments")
    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_total_rollup"


def test_audax_flat_comma_debt_and_equity_classified():
    """Older flat comma-delimited Audax identifiers classify by instrument text."""
    debt = classify_identifier(
        "0001633858",
        "A Place For Mom, Senior Secured Term Loan, Due 2/10/2026",
    )
    equity = classify_identifier(
        "0001633858",
        "A1 Garage Door Service, Equity Securities, Class A Common Units",
    )
    assert debt["wrapper_family"] == "debt"
    assert debt["wrapper_disposition"] == "debt_position_leaf"
    assert equity["wrapper_family"] == "equity"
    assert equity["wrapper_disposition"] == "equity_position_leaf"


def test_audax_cash_equivalent_is_non_private():
    """Cash-equivalent rows are classified as non-private-market."""
    result = classify_identifier("0001633858", "Cash Equivalents")
    assert result["wrapper_family"] == "cash"
    assert result["wrapper_disposition"] == "non_private_market"


def test_audax_registered_in_supported_ciks():
    """Audax Credit BDC CIK is in the supported wrapper registry."""
    assert "0001633858" in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Antares Strategic Credit Fund wrapper (CIK 0001993402)
# ---------------------------------------------------------------------------


ANTARES_STRATEGIC_CREDIT_CIK = "0001993402"


def test_antares_asset_type_debt_leaf_classified():
    result = classify_identifier(
        ANTARES_STRATEGIC_CREDIT_CIK,
        "Investments - non-controlled/non-affiliated Secured Debt Aerospace and Defense "
        "Bleriot US Bidco Inc. Asset Type First Lien Term Loan Reference Rate and Spread "
        "S + 2.50% Interest Rate 6.15% Maturity Date 10/31/2030",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"
    assert result["wrapper_position_key"]


def test_antares_equity_asset_type_leaf_classified():
    result = classify_identifier(
        ANTARES_STRATEGIC_CREDIT_CIK,
        "Investments - non-controlled/non-affiliated Equity Investments Diversified "
        "Consumer Services FourChildren Blocker Aggregator, LP Asset Type Common",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_antares_commitment_type_leaf_classified():
    result = classify_identifier(
        ANTARES_STRATEGIC_CREDIT_CIK,
        "Investments - non-controlled/non-affiliated DT1 Midco Corp Commitment Type "
        "DelayedDraw Term Loan Commitment Expiration Date 6/4/2027",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_antares_totals_and_cash_are_not_private_leaves():
    total = classify_identifier(
        ANTARES_STRATEGIC_CREDIT_CIK,
        "Investments - non-controlled/non-affiliated Total Unfunded Commitments",
    )
    cash = classify_identifier(
        ANTARES_STRATEGIC_CREDIT_CIK,
        "Cash and Cash Equivalents BlackRock Liquidity T-Fund - Institutional Shares",
    )

    assert total["wrapper_disposition"] in {"aggregate", "mixed_total_rollup"}
    assert cash["wrapper_disposition"] == "non_private_market"


def test_antares_registered_in_supported_ciks():
    assert ANTARES_STRATEGIC_CREDIT_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Antares Private Credit Fund wrapper (CIK 0001976336)
# ---------------------------------------------------------------------------


ANTARES_PRIVATE_CREDIT_CIK = "0001976336"


def test_antares_private_asset_type_debt_leaf_classified():
    result = classify_identifier(
        ANTARES_PRIVATE_CREDIT_CIK,
        "Investments - non-controlled/non-affiliated Secured Debt Aerospace and Defense "
        "Bleriot US Bidco Inc. Asset Type First Lien Term Loan Reference Rate and Spread "
        "S + 2.50% Interest Rate 6.17% Maturity Date 10/31/2030",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"
    assert result["wrapper_position_key"]


def test_antares_private_assets_type_plural_leaf_classified():
    result = classify_identifier(
        ANTARES_PRIVATE_CREDIT_CIK,
        "Secured Debt Professional Services HSI Halo Acquisition Inc. Assets Type "
        "First Lien Term Loan Reference Rate and Spread S + 5.00% Interest Rate "
        "9.13% Maturity Date 6/30/2031",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_antares_private_equity_asset_type_leaf_classified():
    result = classify_identifier(
        ANTARES_PRIVATE_CREDIT_CIK,
        "Investments - non-controlled/non-affiliated Equity Investments Containers "
        "and Packaging KPCI Co-Invest 2, LP Asset Type LP Units",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_antares_private_commitment_type_leaf_classified():
    result = classify_identifier(
        ANTARES_PRIVATE_CREDIT_CIK,
        "Investments\u2014non-controlled/non-affiliated Inhabitiq Inc. Commitment Type "
        "Delayed Draw Term Loan Commitment Expiration Date 1/11/2027",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_antares_private_totals_cash_and_headings_are_not_private_leaves():
    unfunded_total = classify_identifier(
        ANTARES_PRIVATE_CREDIT_CIK,
        "Investments\u2014non-controlled/non-affiliated Unfunded Commitments",
    )
    cash = classify_identifier(
        ANTARES_PRIVATE_CREDIT_CIK,
        "Cash and Cash Equivalents BlackRock Liquidity T-Fund - Institutional Shares",
    )
    industry_heading = classify_identifier(
        ANTARES_PRIVATE_CREDIT_CIK,
        "Investments - non-controlled/non-affiliated Secured Debt IT Services",
    )
    total_equity = classify_identifier(
        ANTARES_PRIVATE_CREDIT_CIK,
        "Investments - non-controlled/non-affiliated Total Equity Investments",
    )
    total_debt = classify_identifier(
        ANTARES_PRIVATE_CREDIT_CIK,
        "Total Secured Debt Investments",
    )

    assert unfunded_total["wrapper_disposition"] in {"aggregate", "mixed_total_rollup"}
    assert cash["wrapper_disposition"] == "non_private_market"
    assert not industry_heading["wrapper_disposition"].endswith("_position_leaf")
    assert total_equity["wrapper_disposition"] == "aggregate"
    assert total_debt["wrapper_disposition"] == "aggregate"


def test_antares_private_registered_in_supported_ciks():
    assert ANTARES_PRIVATE_CREDIT_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# TCG BDC II wrapper (CIK 0001702510)
# ---------------------------------------------------------------------------


TCG_BDC_II_CIK = "0001702510"


def test_tcg_bdc_pipe_debt_leaf_classified():
    result = classify_identifier(
        TCG_BDC_II_CIK,
        "Investment | Non-Affiliated Issuer | First Lien Debt | Alpine "
        "Corporation II | Transportation: Cargo 2",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"
    assert result["wrapper_position_key"]


def test_tcg_bdc_comma_debt_leaf_with_internal_commas_classified():
    result = classify_identifier(
        TCG_BDC_II_CIK,
        "Investment, Non-Affiliated Issuer, First Lien Debt, BlueCat Networks, "
        "Inc. (Canada), High Tech Industries",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_tcg_bdc_equity_leaf_classified():
    result = classify_identifier(
        TCG_BDC_II_CIK,
        "Investment | Affiliated Issuer | Equity Investments | Align Precision "
        "Group, LLC | Aerospace & Defense 1",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_tcg_bdc_category_header_is_not_leaf():
    result = classify_identifier(
        TCG_BDC_II_CIK,
        "Investment | Non-Affiliated Issuer | First Lien Debt",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "aggregate"
    assert result["wrapper_position_key"] == ""


def test_tcg_bdc_total_power_issuer_survives_as_leaf():
    result = classify_identifier(
        TCG_BDC_II_CIK,
        "Investment | Non-Affiliated Issuer | First Lien Debt | Total Power "
        "Limited (Canada) | Energy: Electricity",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_tcg_bdc_registered_in_supported_ciks():
    assert TCG_BDC_II_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# T. Rowe Price OHA Select Private Credit Fund wrapper (CIK 0001901164)
# ---------------------------------------------------------------------------


TRP_OHA_SELECT_CIK = "0001901164"


def test_trp_oha_pipe_affiliation_leaf_key_strips_affiliation():
    result = classify_identifier(
        TRP_OHA_SELECT_CIK,
        "123Dentist Inc. 1 | Non-Affiliated Issuer",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"
    assert result["wrapper_position_key"] == "123dentist inc 1"


def test_trp_oha_comma_affiliation_leaf_key_strips_prefix():
    result = classify_identifier(
        TRP_OHA_SELECT_CIK,
        "Investment, Unaffiliated Issuer, Alera Group, Inc., Second Lien",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"] == "alera group inc second lien"


def test_trp_oha_total_investments_is_not_leaf():
    result = classify_identifier(TRP_OHA_SELECT_CIK, "Total Investments")

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_total_rollup"


def test_trp_oha_bare_issuer_styles_survive_as_leaves():
    mantech = classify_identifier(TRP_OHA_SELECT_CIK, "Mantech International CP 1")
    music = classify_identifier(TRP_OHA_SELECT_CIK, "Global Music Rights 2")
    consultant = classify_identifier(TRP_OHA_SELECT_CIK, "Geosyntec Consultants 1")

    assert mantech["wrapper_disposition"] == "mixed_position_leaf"
    assert music["wrapper_disposition"] == "mixed_position_leaf"
    assert consultant["wrapper_disposition"] == "mixed_position_leaf"


def test_trp_oha_registered_in_supported_ciks():
    assert TRP_OHA_SELECT_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Jefferies Credit Partners BDC wrapper (CIK 0001959604)
# ---------------------------------------------------------------------------


JEFFERIES_CREDIT_PARTNERS_CIK = "0001959604"


def test_jefferies_hierarchy_debt_leaf_classified():
    result = classify_identifier(
        JEFFERIES_CREDIT_PARTNERS_CIK,
        "Non-Controlled/Non-Affiliated Portfolio Company Investments First Lien "
        "Debt Investments Insurance Koala Investment Holdings, Inc. Investment "
        "Type First Lien Delayed Draw Term Loan Reference Rate and Spread S + "
        "4.50% Maturity Date 8/30/2032",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_jefferies_hierarchy_equity_lp_leaf_classified():
    result = classify_identifier(
        JEFFERIES_CREDIT_PARTNERS_CIK,
        "Non-Controlled/Non-Affiliated Portfolio Company Investments Equity "
        "Investments L.P Interests Commercial Services & Supplies Firebird "
        "Co-Invest L.P Investment Type L.P Interest",
    )

    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"


def test_jefferies_stripped_portfolio_company_leaf_classified():
    result = classify_identifier(
        JEFFERIES_CREDIT_PARTNERS_CIK,
        "Portfolio Company GS AcquisitionCo, Inc. Investment Type First Lien "
        "Delayed Draw Term Loan",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_jefferies_totals_and_unfunded_commitments_are_not_leaves():
    debt_total = classify_identifier(
        JEFFERIES_CREDIT_PARTNERS_CIK,
        "Non-Controlled/Non-Affiliated Portfolio Company Investments First Lien "
        "Debt Investments Total non-controlled-non-affiliated Portfolio Company "
        "debt investments",
    )
    unfunded = classify_identifier(
        JEFFERIES_CREDIT_PARTNERS_CIK,
        "Total Unfunded Portfolio Company Commitments",
    )
    equity_total = classify_identifier(
        JEFFERIES_CREDIT_PARTNERS_CIK,
        "Non-controlled-non-affiliated Portfolio company debt investments "
        "Equity Investments Preferred Stock Total non-controlled-non-affiliated "
        "Portfolio Company investments",
    )
    industry_heading = classify_identifier(
        JEFFERIES_CREDIT_PARTNERS_CIK,
        "Non-Controlled/Non-Affiliated Portfolio Company Investments First Lien "
        "Debt Investments Services: Consumer",
    )

    assert debt_total["wrapper_disposition"] in {"aggregate", "debt_total_rollup"}
    assert unfunded["wrapper_disposition"] == "aggregate"
    assert equity_total["wrapper_disposition"] == "aggregate"
    assert not industry_heading["wrapper_disposition"].endswith("_position_leaf")


def test_jefferies_registered_in_supported_ciks():
    assert JEFFERIES_CREDIT_PARTNERS_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# Diameter Credit Co wrapper (CIK 0001916099)
# ---------------------------------------------------------------------------


DIAMETER_CREDIT_CIK = "0001916099"


def test_diameter_credit_debt_leaf_classified_from_hierarchy_identifier():
    result = classify_identifier(
        DIAMETER_CREDIT_CIK,
        "Investments Non-Controlled/Non-Affiliated First Lien Debt Financial Services "
        "BDO USA, P.C. Term Loan Interest Rate 11.33% Reference Rate SOFR Spread "
        "6.00% Maturity Date 8/31/2028",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]
    assert result["wrapper_structured_leaf_key"]


def test_diameter_credit_position_key_ignores_current_coupon_drift():
    first = classify_identifier(
        DIAMETER_CREDIT_CIK,
        "Investments Non-Controlled/Non-Affiliated First Lien Debt Financial Services "
        "BDO USA, P.C. Term Loan Interest Rate 11.33% Reference Rate SOFR Spread "
        "6.00% Maturity Date 8/31/2028",
    )
    second = classify_identifier(
        DIAMETER_CREDIT_CIK,
        "Investments Non-Controlled/Non-Affiliated First Lien Debt Financial Services "
        "BDO USA, P.C. Term Loan Interest Rate 11.34% Reference Rate SOFR Spread "
        "6.00% Maturity Date 8/31/2028",
    )

    assert first["wrapper_position_key"] == second["wrapper_position_key"]


def test_diameter_credit_position_key_ignores_acquisition_date_lot_metadata():
    without_date = classify_identifier(
        DIAMETER_CREDIT_CIK,
        "Investments Non-Controlled/Non-Affiliated First Lien Debt Software "
        "xAI Corp Term Loan Reference Rate SOFR Spread 7.25% Maturity Date 12/9/2028",
    )
    with_date = classify_identifier(
        DIAMETER_CREDIT_CIK,
        "Investments Non-Controlled/Non-Affiliated First Lien Debt Software "
        "xAI Corp Term Loan Reference Rate SOFR Spread 7.25% Acquisition Date "
        "12/8/2025 Maturity Date 12/9/2028",
    )

    assert without_date["wrapper_position_key"] == with_date["wrapper_position_key"]


def test_diameter_credit_sector_category_is_not_leaf():
    result = classify_identifier(
        DIAMETER_CREDIT_CIK,
        "Investments Non-Controlled/Non-Affiliated First Lien Debt Financial Services",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] in {"aggregate", "debt_category_rollup"}
    assert result["wrapper_position_key"] == ""


def test_diameter_credit_cash_totals_are_non_private_market():
    result = classify_identifier(DIAMETER_CREDIT_CIK, "Total Cash and Cash Equivalents")

    assert result["wrapper_disposition"] == "non_private_market"


def test_diameter_credit_malformed_preferred_total_is_not_leaf():
    result = classify_identifier(
        DIAMETER_CREDIT_CIK,
        "Investments Non-Controlled/Non-Affiliated Preferred Equity"
        "Investments Non-Controlled/Non-Affiliated Total Preferred Equity",
    )

    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "aggregate"
    assert result["wrapper_position_key"] == ""


def test_diameter_credit_equity_fund_leaf_classified():
    result = classify_identifier(
        DIAMETER_CREDIT_CIK,
        "Investments Non-Controlled/Non-Affiliated Equity Other Equity Financial Services "
        "Constellation Wealth Capital Fund II LP",
    )

    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"
    assert result["wrapper_position_key"]


def test_diameter_credit_registered_in_supported_ciks():
    assert DIAMETER_CREDIT_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# T Series Middle Market Loan Fund LLC wrapper (CIK 0001885968)
# ---------------------------------------------------------------------------


T_SERIES_BDC_CIK = "0001885968"


def test_t_series_bdc_debt_leaf_classified_from_hierarchy_identifier():
    result = classify_identifier(
        T_SERIES_BDC_CIK,
        "Debt Investments - non-controlled/non-affiliated Software "
        "Anaplan, Inc. First Lien Debt Reference Rate and Spread S + 4.50% "
        "Interest Rate 8.70% Maturity Date 06/21/2029",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_t_series_bdc_axis_label_variant_classified():
    result = classify_identifier(
        T_SERIES_BDC_CIK,
        "Investment, Identifier [Axis]: Debt Investments - non-controlled/non-affiliated "
        "Health Care Providers & Services Pareto Health Intermediate Holdings, Inc. "
        "First Lien Debt Reference Rate and Spread S + 4.75% Interest Rate 0.0875 "
        "Maturity Date 06/01/2029",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_t_series_bdc_affiliation_spelling_variants_classified():
    spaced = classify_identifier(
        T_SERIES_BDC_CIK,
        "Debt Investments - non-controlled/non - affiliated Software "
        "Fullsteam Operations, LLC First Lien Debt Reference Rate and Spread "
        "S + 5.25% Interest Rate 8.89% Maturity Date 08/08/2031",
    )
    affiliated = classify_identifier(
        T_SERIES_BDC_CIK,
        "Debt Investments - non-controlled/affiliated Professional Services "
        "KWOR Acquisition, Inc. Other Debt Reference Rate and Spread 8.00% PIK "
        "Interest Rate 12.20% Maturity Date 02/28/2030",
    )

    assert spaced["wrapper_disposition"] == "debt_position_leaf"
    assert affiliated["wrapper_disposition"] == "debt_position_leaf"


def test_t_series_bdc_equity_leaf_classified():
    result = classify_identifier(
        T_SERIES_BDC_CIK,
        "Equity Investments - non-controlled/non-affiliated Insurance Services "
        "Amerilife Holdings, LLC Common Equity Acquisition Date 09/01/2022",
    )

    assert result["wrapper_family"] == "equity"
    assert result["wrapper_disposition"] == "equity_position_leaf"
    assert result["wrapper_position_key"]


def test_t_series_bdc_cash_total_and_bare_issuer_are_not_leaves():
    cash = classify_identifier(T_SERIES_BDC_CIK, "J.P. Morgan US Govt Money Market Fund")
    total = classify_identifier(T_SERIES_BDC_CIK, "Total Investments")
    bare = classify_identifier(T_SERIES_BDC_CIK, "Anaplan, Inc.")

    assert cash["wrapper_disposition"] == "non_private_market"
    assert total["wrapper_disposition"] in {"aggregate", "debt_total_rollup"}
    assert bare["wrapper_disposition"] == ""


def test_t_series_bdc_position_key_ignores_current_coupon_drift_only():
    first = classify_identifier(
        T_SERIES_BDC_CIK,
        "Debt Investments - non-controlled/non-affiliated Software "
        "Anaplan, Inc. First Lien Debt Reference Rate and Spread S + 4.50% "
        "Interest Rate 8.70% Maturity Date 06/21/2029",
    )
    second = classify_identifier(
        T_SERIES_BDC_CIK,
        "Debt Investments - non-controlled/non-affiliated Software "
        "Anaplan, Inc. First Lien Debt Reference Rate and Spread S + 4.50% "
        "Interest Rate 8.90% Maturity Date 06/21/2029",
    )
    different_maturity = classify_identifier(
        T_SERIES_BDC_CIK,
        "Debt Investments - non-controlled/non-affiliated Software "
        "Anaplan, Inc. First Lien Debt Reference Rate and Spread S + 4.50% "
        "Interest Rate 8.70% Maturity Date 06/21/2030",
    )

    assert first["wrapper_position_key"] == second["wrapper_position_key"]
    assert first["wrapper_position_key"] != different_maturity["wrapper_position_key"]


def test_t_series_bdc_registered_in_supported_ciks():
    assert T_SERIES_BDC_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# AB Private Credit Investors Corp wrapper (CIK 0001634452)
# ---------------------------------------------------------------------------


AB_PRIVATE_CREDIT_INVESTORS_CIK = "0001634452"


def test_ab_private_credit_investors_pipe_debt_leaf_classified():
    result = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Corporate Debt | 1st Lien/Senior Secured Debt | "
        "Degreed, Inc| Software & Tech Services | Delayed Draw Term Loan| "
        "10.92% (S + 5.50%; 1.00% PIK; 1.00% Floor)| 05/29/2026",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_ab_private_credit_investors_alternate_debt_prefix_classified():
    result = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. 1st Lien/Senior Secured Debt | Gryphon Redwood Acquisition LLC | "
        "Software & Tech Services | Delayed Draw Term Loan | "
        "14.58% (S + 4.00%; 6.00% PIK; 1.00% Floor) | 09/16/2028",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_ab_private_credit_investors_equity_fund_and_warrant_leaves_classified():
    equity = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Common Stock | Artemis Investor Holdings, LLC | "
        "Class A Units | Services | 1/22/2021",
    )
    fund = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Investment Companies | AB Equity Investors, L.P. | "
        "LP Interests | Investment Companies",
    )
    warrant = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Warrants | Degreed, Inc. | Common Warrants | "
        "Software & Tech Services | 8/31/2022",
    )

    assert equity["wrapper_family"] == "equity"
    assert equity["wrapper_disposition"] == "equity_position_leaf"
    assert fund["wrapper_family"] == "fund"
    assert fund["wrapper_disposition"] == "fund_position_leaf"
    assert warrant["wrapper_family"] == "warrant"
    assert warrant["wrapper_disposition"] == "warrant_position_leaf"


def test_ab_private_credit_investors_category_and_cash_rows_not_leaves():
    debt_category = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "Canadian 1st Lien/Senior Secured Debt",
    )
    stock_category = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Common Stock - 1.52%",
    )
    cash = classify_identifier(AB_PRIVATE_CREDIT_INVESTORS_CIK, "Cash Equivalents")

    assert debt_category["wrapper_family"] == "debt"
    assert debt_category["wrapper_disposition"] == "aggregate"
    assert debt_category["wrapper_position_key"] == ""
    assert stock_category["wrapper_family"] == "equity"
    assert stock_category["wrapper_disposition"] == "aggregate"
    assert stock_category["wrapper_position_key"] == ""
    assert cash["wrapper_disposition"] == "non_private_market"


def test_ab_private_credit_investors_preserves_lot_suffix_in_position_key():
    first = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Corporate Debt | 1st Lien Senior Secured Debt | "
        "American Physician Partners LLC | Healthcare & HCIT | Term Loan | "
        "14.67% | S + 6.75% | 3.50% PIK | 1.00% Floor | 02/15/2023 | One",
    )
    second = classify_identifier(
        AB_PRIVATE_CREDIT_INVESTORS_CIK,
        "U.S. Corporate Debt | 1st Lien Senior Secured Debt | "
        "American Physician Partners LLC | Healthcare & HCIT | Term Loan | "
        "14.67% | S + 6.75% | 3.50% PIK | 1.00% Floor | 02/15/2023 | Two",
    )

    assert first["wrapper_disposition"] == "debt_position_leaf"
    assert second["wrapper_disposition"] == "debt_position_leaf"
    assert first["wrapper_position_key"] != second["wrapper_position_key"]


def test_ab_private_credit_investors_registered_in_supported_ciks():
    assert AB_PRIVATE_CREDIT_INVESTORS_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# New Mountain Private Credit Fund wrapper (CIK 0002037804)
# ---------------------------------------------------------------------------


NEW_MOUNTAIN_PRIVATE_CREDIT_CIK = "0002037804"


def test_new_mountain_pipe_debt_leaf_strips_affiliation_suffix():
    result = classify_identifier(
        NEW_MOUNTAIN_PRIVATE_CREDIT_CIK,
        "AAH Topco, LLC | First Lien 1 | Non-Affiliated Issuer",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"] == "aah topco llc first lien 1"


def test_new_mountain_comma_debt_leaf_classified():
    result = classify_identifier(
        NEW_MOUNTAIN_PRIVATE_CREDIT_CIK,
        "Centegix Intermediate II, LLC, First Lien - Undrawn 1",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"]


def test_new_mountain_equity_leaf_classified():
    preferred = classify_identifier(
        NEW_MOUNTAIN_PRIVATE_CREDIT_CIK,
        "ACI Parent Inc. | Preferred shares | Non-Affiliated Issuer",
    )
    common = classify_identifier(
        NEW_MOUNTAIN_PRIVATE_CREDIT_CIK,
        "Ambrosia Topco, LLC | Class A-1 common units 1",
    )
    ordinary = classify_identifier(
        NEW_MOUNTAIN_PRIVATE_CREDIT_CIK,
        "Ambrosia Holdco Corp, Ordinary shares 1",
    )

    assert preferred["wrapper_family"] == "equity"
    assert preferred["wrapper_disposition"] == "equity_position_leaf"
    assert common["wrapper_family"] == "equity"
    assert common["wrapper_disposition"] == "equity_position_leaf"
    assert ordinary["wrapper_family"] == "equity"
    assert ordinary["wrapper_disposition"] == "equity_position_leaf"


def test_new_mountain_business_line_position_uses_mixed_leaf():
    result = classify_identifier(
        NEW_MOUNTAIN_PRIVATE_CREDIT_CIK,
        "Accelya Lux Finco S.a r.l. | Business Services",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_new_mountain_single_name_business_line_position_is_leaf():
    result = classify_identifier(
        NEW_MOUNTAIN_PRIVATE_CREDIT_CIK,
        "Denali | Software",
    )

    assert result["wrapper_family"] == "mixed"
    assert result["wrapper_disposition"] == "mixed_position_leaf"


def test_new_mountain_totals_and_cash_are_not_private_leaves():
    total = classify_identifier(NEW_MOUNTAIN_PRIVATE_CREDIT_CIK, "Total Investments")
    cash = classify_identifier(
        NEW_MOUNTAIN_PRIVATE_CREDIT_CIK,
        "Cash and Cash Equivalents First American Government Obligations Fund",
    )

    assert total["wrapper_disposition"] == "mixed_total_rollup"
    assert cash["wrapper_disposition"] == "non_private_market"


def test_new_mountain_registered_in_supported_ciks():
    assert NEW_MOUNTAIN_PRIVATE_CREDIT_CIK in supported_wrapper_ciks()


# ---------------------------------------------------------------------------
# NMF SLF I wrapper (CIK 0001766037)
# ---------------------------------------------------------------------------


NMF_SLF_I_CIK = "0001766037"


def test_nmf_slf_i_pipe_debt_leaf_strips_affiliation_suffix():
    result = classify_identifier(
        NMF_SLF_I_CIK,
        "AAH Topco, LLC, First Lien 1 | Non-Affiliated Issuer",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"
    assert result["wrapper_position_key"] == "aah topco llc first lien 1"


def test_nmf_slf_i_comma_debt_leaf_classified():
    result = classify_identifier(
        NMF_SLF_I_CIK,
        "Associations, Inc., Subordinated 2 | Non-Affiliated Issuer",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_nmf_slf_i_equity_leaf_classified():
    preferred = classify_identifier(
        NMF_SLF_I_CIK,
        "Eclipse Topco, Inc., Preferred Shares | Non-Affiliated Issuer",
    )
    common = classify_identifier(
        NMF_SLF_I_CIK,
        "KWOR Acquisition, Inc., Class A -1 common units | Non-Affiliated Issuer",
    )
    ordinary = classify_identifier(
        NMF_SLF_I_CIK,
        "Notorious Buyer LLC, Ordinary Shares | Non-Affiliated Issuer",
    )

    assert preferred["wrapper_family"] == "equity"
    assert preferred["wrapper_disposition"] == "equity_position_leaf"
    assert common["wrapper_family"] == "equity"
    assert common["wrapper_disposition"] == "equity_position_leaf"
    assert ordinary["wrapper_family"] == "equity"
    assert ordinary["wrapper_disposition"] == "equity_position_leaf"


def test_nmf_slf_i_first_lie_typo_is_debt_leaf():
    result = classify_identifier(
        NMF_SLF_I_CIK,
        "Coyote Buyer, LLC, First Lie 2",
    )

    assert result["wrapper_family"] == "debt"
    assert result["wrapper_disposition"] == "debt_position_leaf"


def test_nmf_slf_i_bare_issuer_not_forced_to_leaf():
    result = classify_identifier(
        NMF_SLF_I_CIK,
        "Affinipay Midco, LLC",
    )

    assert result["wrapper_disposition"] == ""
    assert result["wrapper_position_key"] == ""


def test_nmf_slf_i_totals_and_affiliation_headers_are_not_leaves():
    total = classify_identifier(NMF_SLF_I_CIK, "Total Investments")
    affiliation = classify_identifier(NMF_SLF_I_CIK, "Non-Affiliated Issuer")

    assert total["wrapper_disposition"] == "debt_total_rollup"
    assert total["wrapper_position_key"] == ""
    assert affiliation["wrapper_disposition"] == "aggregate"
    assert affiliation["wrapper_position_key"] == ""


def test_nmf_slf_i_registered_in_supported_ciks():
    assert NMF_SLF_I_CIK in supported_wrapper_ciks()
