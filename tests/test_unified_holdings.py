"""Tests for pipeline.unified_holdings module.

Covers:
- BDC identifier parsing: normal split, no dash, multiple dashes, quantity stripping
- BDC aggregate row detection: named aggregates, bare issuer names, normal holdings
- BDC asset classification: debt keywords, equity keywords, fund keywords, XBRL axis override
- BDC issuer classification: FUND -> FUND, else -> CORPORATE
- N-PORT asset/issuer mapping: all codes, unknown codes
- Index classification: all 4 indices, unclassified, edge cases
- Coupon type inference: Floating, Fixed, blank
- BDC preparation: filtering, column mapping, end-to-end
- N-PORT preparation: Level 3 filter, column mapping, end-to-end
- Full integration: build_unified_holdings
- CLI: --unified flag parsing
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from pipeline.unified_holdings import (
    _AFFILIATION_TAGS,
    _apply_row_corrections,
    _classify_bdc_asset,
    _classify_bdc_issuer,
    _classify_index,
    _classify_nport_asset,
    _classify_nport_issuer,
    _CORRECTABLE_FIELDS,
    _correct_pct_of_net_assets,
    _enforce_schema,
    _infer_coupon_type,
    _INDUSTRY_LABELS,
    _is_bad_issuer_name,
    _is_bdc_aggregate_row,
    _is_named_coinvest,
    _normalize_rate,
    _parse_bdc_identifier,
    _prepare_bdc,
    _prepare_nport,
    _reclassify_named_fund_positions,
    _sql_classify_exposure_type,
    _sql_classify_asset_class,
    _stabilize_classification,
    build_unified_holdings,
    UNIFIED_COLUMNS,
)


# ---------------------------------------------------------------------------
# _parse_bdc_identifier
# ---------------------------------------------------------------------------

class TestParseBdcIdentifier:
    def test_normal_split(self):
        issuer, instrument = _parse_bdc_identifier(
            "Caitec, Inc. - Subordinated Secured Promissory Note"
        )
        assert issuer == "Caitec, Inc."
        assert instrument == "Subordinated Secured Promissory Note"

    def test_no_dash(self):
        issuer, instrument = _parse_bdc_identifier("Caitec, Inc.")
        assert issuer == "Caitec, Inc."
        assert instrument == ""

    def test_multiple_dashes(self):
        issuer, instrument = _parse_bdc_identifier(
            "Acme Corp - First Lien - Term Loan"
        )
        assert issuer == "Acme Corp"
        assert instrument == "First Lien - Term Loan"

    def test_quantity_stripping(self):
        issuer, instrument = _parse_bdc_identifier(
            "ACV Auctions, Inc, - 319,934 shares"
        )
        assert issuer == "ACV Auctions, Inc,"
        assert instrument == "shares"

    def test_dollar_prefix_stripping(self):
        issuer, instrument = _parse_bdc_identifier(
            "Caitec, Inc. - $1,750,000 Subordinated Secured Promissory Note"
        )
        assert issuer == "Caitec, Inc."
        assert instrument == "Subordinated Secured Promissory Note"

    def test_empty_string(self):
        assert _parse_bdc_identifier("") == ("", "")

    def test_none_input(self):
        assert _parse_bdc_identifier(None) == ("", "")

    def test_whitespace_handling(self):
        issuer, instrument = _parse_bdc_identifier(
            "  Acme Corp  -  Term Loan  "
        )
        assert issuer == "Acme Corp"
        assert instrument == "Term Loan"


# ---------------------------------------------------------------------------
# _is_bdc_aggregate_row
# ---------------------------------------------------------------------------

class TestIsBdcAggregateRow:
    def test_non_control_aggregate(self):
        assert _is_bdc_aggregate_row(
            "Non-Control/Non-Affiliate Investments - Net assets"
        )

    def test_total_investments(self):
        assert _is_bdc_aggregate_row("Total Investments")

    def test_affiliate_investments(self):
        assert _is_bdc_aggregate_row("Affiliate Investments at Fair Value")

    def test_control_investments(self):
        assert _is_bdc_aggregate_row("Control Investments")

    def test_affiliation_bucket_with_economic_detail_not_substring_filtered(self):
        assert not _is_bdc_aggregate_row(
            "Construction & Engineering First Lien Senior Secured Term Loan "
            "Non-Affiliate Investments"
        )

    def test_bare_affiliation_header_still_filtered(self):
        assert _is_bdc_aggregate_row("Non-Affiliate Investments")

    def test_subtotal(self):
        assert _is_bdc_aggregate_row("Subtotal - First Lien")

    def test_net_assets(self):
        assert _is_bdc_aggregate_row("Net Assets in excess of other assets")

    def test_bare_issuer_name_kept(self):
        # Bare names are individual holdings, not subtotals
        assert not _is_bdc_aggregate_row("Caitec, Inc.")

    def test_bare_name_with_keywords_kept(self):
        assert not _is_bdc_aggregate_row("Acme Corp First Lien Term Loan")

    def test_normal_holding(self):
        assert not _is_bdc_aggregate_row(
            "Caitec, Inc. - Subordinated Secured Promissory Note"
        )

    # V3 expansion: new aggregate patterns
    def test_new_aggregate_investment_debt_investments(self):
        assert _is_bdc_aggregate_row("Investment Debt Investments - 1st Lien")

    def test_new_aggregate_cash_equivalents(self):
        assert _is_bdc_aggregate_row("Cash and Cash Equivalents")

    def test_new_aggregate_liabilities(self):
        assert _is_bdc_aggregate_row("Liabilities in Excess of Other Assets")

    def test_new_aggregate_total_fair_value(self):
        assert _is_bdc_aggregate_row("Total Fair Value")

    def test_new_aggregate_unfunded(self):
        assert _is_bdc_aggregate_row("Unfunded Commitments to Third Parties")

    def test_new_aggregate_placeholder(self):
        assert _is_bdc_aggregate_row("Placeholder entry for XBRL")

    def test_legitimate_name_not_filtered(self):
        # "Cash & Carry Corp" should NOT be filtered (not matching patterns)
        assert not _is_bdc_aggregate_row("Cash & Carry Corp - Term Loan")

    def test_case_insensitivity(self):
        assert _is_bdc_aggregate_row("NON-CONTROL/NON-AFFILIATE INVESTMENTS")

    def test_empty_string(self):
        assert _is_bdc_aggregate_row("")

    def test_none_input(self):
        assert _is_bdc_aggregate_row(None)

    # Aggregate-only XBRL filer patterns
    def test_assets_in_excess(self):
        assert _is_bdc_aggregate_row("Assets in Excess of Other Liabilities")

    def test_investment_portfolio(self):
        assert _is_bdc_aggregate_row("Investment Portfolio")

    def test_total_investment_portfolio(self):
        assert _is_bdc_aggregate_row("Total Investment Portfolio")

    def test_total_mutual_funds(self):
        assert _is_bdc_aggregate_row("Total Mutual Funds")

    def test_total_us_treasury(self):
        assert _is_bdc_aggregate_row("Total U.S. Treasury")

    def test_percentage_ending_subtotal(self):
        assert _is_bdc_aggregate_row("Debt Investment 96.8%")

    def test_percentage_with_dash(self):
        assert _is_bdc_aggregate_row("United States - 1.60%")

    def test_percentage_debt_investments(self):
        assert _is_bdc_aggregate_row("Debt Investments - 88.71%")

    def test_percentage_geography(self):
        assert _is_bdc_aggregate_row("Investment Canada - 7.56%")

    def test_debt_investments_comma_industry(self):
        assert _is_bdc_aggregate_row("Debt Investments, Insurance")

    def test_debt_investment_singular_exact(self):
        assert _is_bdc_aggregate_row("Debt Investment")

    def test_real_holding_with_pct_in_middle_kept(self):
        """Holdings with pct in the middle (not end) should be kept."""
        assert not _is_bdc_aggregate_row(
            "Acme Corp - 8.5% Senior Note Due 2028"
        )

    # Leaked subtotal patterns found in position-return analysis (2026-04-03)
    def test_total_debt_investments_substring(self):
        assert _is_bdc_aggregate_row("Total Debt Investments, First Lien Debt")

    def test_total_secured_debt(self):
        assert _is_bdc_aggregate_row("Total Secured Debt Investments")

    def test_total_bank_debt(self):
        assert _is_bdc_aggregate_row("Total Bank Debt/Senior Secured Loans")

    def test_total_equipment_financing(self):
        assert _is_bdc_aggregate_row(
            "Equipment Financing | Total Equipment Financing"
        )

    def test_total_unsecured(self):
        assert _is_bdc_aggregate_row("Total Unsecured Debt")

    def test_first_lien_secured_debt_exact(self):
        assert _is_bdc_aggregate_row("First Lien - Secured Debt")

    def test_second_lien_secured_debt_exact(self):
        assert _is_bdc_aggregate_row("Second Lien - Secured Debt")

    def test_unsecured_debt_exact(self):
        assert _is_bdc_aggregate_row("Unsecured Debt")

    def test_us_1st_lien_category(self):
        assert _is_bdc_aggregate_row("U.S. 1st Lien/Junior Secured Debt")

    # Equity category subtotals (leaked pipe-delimited headers)
    def test_total_common_equity_pipe(self):
        assert _is_bdc_aggregate_row(
            "Common Equity/Equity Interests/Warrants | "
            "Total Common Equity/Equity Interests/Warrants"
        )

    def test_total_common_equity_with_pct(self):
        assert _is_bdc_aggregate_row(
            "Common Equity/Equity Interests/Warrants-63.4% | "
            "Total Common Equity/Equity Interests/Warrants"
        )

    def test_total_preferred_equity_pipe(self):
        assert _is_bdc_aggregate_row(
            "Preferred Equity | Total Preferred Equity"
        )

    def test_total_preferred_equity_bare(self):
        assert _is_bdc_aggregate_row("Total Preferred Equity")

    def test_total_equity_slash(self):
        assert _is_bdc_aggregate_row("Total Equity/Other")

    def test_total_equity_investment(self):
        assert _is_bdc_aggregate_row("Total equity investment")

    def test_real_company_with_total_kept(self):
        """'Total Safety Holdings LLC' should NOT be filtered."""
        assert not _is_bdc_aggregate_row("Total Safety Holdings LLC")

    def test_real_company_total_access_elevator_kept(self):
        """'Total Access Elevator, LLC' should NOT be filtered."""
        assert not _is_bdc_aggregate_row(
            "Total Access Elevator, LLC - Common Equity"
        )

    # Bare instrument-type headers (Kennedy Lewis, SLR HC BDC, Ares Core Infra)
    def test_first_and_second_lien_debt_exact(self):
        assert _is_bdc_aggregate_row("First and Second Lien Debt")

    def test_bank_debt_senior_secured_loans_exact(self):
        assert _is_bdc_aggregate_row("Bank Debt/Senior Secured Loans")

    def test_senior_subordinated_loans_exact(self):
        assert _is_bdc_aggregate_row("Senior subordinated loans")

    def test_portfolio_investments_and_cash(self):
        assert _is_bdc_aggregate_row("Portfolio Investments and Cash Equivalents")

    def test_liabilities_less_other_assets(self):
        assert _is_bdc_aggregate_row("Liabilities Less Other Assets")

    # Industry-prefixed subtotals (suffix match)
    def test_industry_first_and_second_lien_debt(self):
        assert _is_bdc_aggregate_row(
            "Oil, Gas & Consumable Fuels First and Second Lien Debt"
        )

    def test_industry_equity_investments(self):
        assert _is_bdc_aggregate_row(
            "Commercial Services & Supplies Equity Investments"
        )

    # HPS/Twin Brook are real N-PORT fund-of-funds allocations, NOT subtotals
    def test_hps_senior_secured_loan_kept(self):
        """HPS Industrials Senior Secured Loan is a real pooled vehicle."""
        assert not _is_bdc_aggregate_row("HPS Industrials Senior Secured Loan")

    def test_twin_brook_senior_secured_kept(self):
        """Twin Brook Healthcare Senior Secured Loan is a real pooled vehicle."""
        assert not _is_bdc_aggregate_row("Twin Brook Healthcare Senior Secured Loan")

    # Real positions with rate/maturity AFTER instrument type -- NOT filtered
    def test_real_position_with_rate_kept(self):
        """Real position with SOFR spread after instrument type should NOT be filtered."""
        assert not _is_bdc_aggregate_row(
            "Globe Electric Company Inc First and Second Lien Debt "
            "SOFR Spread 6.50 % Interest Rate 11.25% Due 3/15/2029"
        )

    def test_real_position_equity_investments_with_rate_kept(self):
        """Real equity position with details after should NOT be filtered."""
        assert not _is_bdc_aggregate_row(
            "Acme Corp Equity Investments SOFR Spread 5.00% Due 2028"
        )

    def test_real_company_first_lien_loan_kept(self):
        """Real first lien loan position should NOT be filtered."""
        assert not _is_bdc_aggregate_row(
            "Acme Corp, First Lien Senior Secured Term Loan"
        )

    # --- 2026-04-09 audit: affiliation subtotals ---
    def test_total_controlled_affiliates(self):
        assert _is_bdc_aggregate_row("Total Controlled Affiliates")

    def test_total_affiliated_investments(self):
        assert _is_bdc_aggregate_row("Total Affiliated Investments")

    def test_total_controlled_investments(self):
        assert _is_bdc_aggregate_row("Total Controlled Investments")

    def test_total_non_controlled_non_affiliated(self):
        assert _is_bdc_aggregate_row(
            "Total Non Controlled Non Affiliated Debt Investments"
        )

    # --- 2026-04-09 audit: fund-level aggregates ---
    def test_investment_fund_after_cash(self):
        assert _is_bdc_aggregate_row(
            "Investment Fund After Cash & Cash Equivalents (195.60%)"
        )

    def test_portfolio_company_investment_in_securities(self):
        assert _is_bdc_aggregate_row(
            "Portfolio Company Investment in Securities"
        )

    def test_five_largest_loan_exposures(self):
        assert _is_bdc_aggregate_row(
            "Five Largest Loan Exposures To Borrowers"
        )

    def test_investments_in_controlled_affiliated(self):
        assert _is_bdc_aggregate_row(
            "Investments in Controlled, Affiliated Portfolio Companies"
        )

    def test_net_asset_value_at_fair_value(self):
        assert _is_bdc_aggregate_row(
            "Joint Venture Net Asset Value at Fair Value"
        )

    def test_cash_and_investments_exact(self):
        assert _is_bdc_aggregate_row("Cash and Investments")

    # --- 2026-04-09 audit: standalone category headers (exact match) ---
    def test_first_lien_secured_debt_exact(self):
        assert _is_bdc_aggregate_row("First Lien Secured Debt")

    def test_first_lien_senior_secured_debt_exact(self):
        assert _is_bdc_aggregate_row("First Lien/Senior Secured Debt")

    # --- 2026-04-09 audit: smart "Total {Industry}" filter ---
    def test_total_software_industry_subtotal(self):
        assert _is_bdc_aggregate_row("Total Software")

    def test_total_healthcare_pharma_subtotal(self):
        assert _is_bdc_aggregate_row("Total Healthcare & Pharmaceuticals")

    def test_total_consumer_services_subtotal(self):
        assert _is_bdc_aggregate_row("Total Consumer Services")

    def test_total_machinery_subtotal(self):
        assert _is_bdc_aggregate_row("Total Machinery")

    def test_total_media_subtotal(self):
        assert _is_bdc_aggregate_row("Total Media")

    # False-positive protection: real companies with "Total" in name
    def test_total_petal_card_inc_kept(self):
        assert not _is_bdc_aggregate_row("Total Petal Card, Inc.")

    def test_total_bestow_inc_kept(self):
        assert not _is_bdc_aggregate_row("Total Bestow, Inc.")

    def test_total_expert_inc_kept(self):
        assert not _is_bdc_aggregate_row("Total Expert Inc.")

    def test_total_fleet_solutions_llc_kept(self):
        assert not _is_bdc_aggregate_row("TOTAL FLEET SOLUTIONS, LLC")

    def test_total_openly_holdings_kept(self):
        assert not _is_bdc_aggregate_row("Total Openly Holdings Corp.")

    def test_total_with_term_loan_kept(self):
        """'Total X Term Loan' is a real position, not a subtotal."""
        assert not _is_bdc_aggregate_row("Total Access Elevator, LLC - Term Loan")

    # --- pipe-segment "Total {Industry}" subtotals ---
    def test_pipe_total_automotive_filtered(self):
        """Last pipe-segment 'Total Automotive' is an industry subtotal."""
        assert _is_bdc_aggregate_row(
            "Corporate Bonds | Automotive | Total Automotive"
        )

    def test_pipe_total_technology_filtered(self):
        """Last pipe-segment 'Total Technology' is an industry subtotal."""
        assert _is_bdc_aggregate_row(
            "Corporate Bonds | Technology | Total Technology"
        )

    def test_pipe_total_healthcare_filtered(self):
        """Last pipe-segment 'Total Healthcare' is an industry subtotal."""
        assert _is_bdc_aggregate_row(
            "Senior Secured | Healthcare | Total Healthcare"
        )

    def test_pipe_total_access_elevator_inc_kept(self):
        """Pipe-segment with 'Inc.' is a real company, not a subtotal."""
        assert not _is_bdc_aggregate_row(
            "First Lien | Total Access Elevator, Inc."
        )

    def test_pipe_total_solutions_holdings_llc_kept(self):
        """Pipe-segment with 'Holdings' and 'LLC' is a real company."""
        assert not _is_bdc_aggregate_row(
            "Debt | Total Solutions Holdings LLC"
        )

    # --- Non-control dimension-path false positive fix (2026-05-04) ---
    def test_long_noncontrol_dimension_path_kept(self):
        """Long dimension-path identifier (>=150 chars) with 'non-controlled' should NOT be filtered."""
        long_id = (
            "Non-Controlled/Non-Affiliated Investments Senior Secured First Lien Loans "
            "Industry Commercial Services & Supplies Company Advanced Web Technologies "
            "Holding Company Delayed Draw SOFR Spread 5.75"
        )
        assert len(long_id) >= 150  # sanity check
        assert not _is_bdc_aggregate_row(long_id)

    def test_short_noncontrol_without_entity_signals_filtered(self):
        """Short 'non-control' without entity-name signals should be filtered."""
        assert _is_bdc_aggregate_row("Non-Control/Non-Affiliate Debt")

    def test_medium_noncontrol_without_entity_signals_filtered(self):
        """Medium-length non-control identifier (no company name) should be filtered."""
        assert _is_bdc_aggregate_row(
            "Non-Controlled/Non-Affiliated Investments, Healthcare & Pharmaceuticals, "
            "First Lien - Secured Debt"
        )

    def test_short_noncontrol_with_llc_signal_kept(self):
        """Short 'non-control' with LLC signal should NOT be filtered."""
        assert not _is_bdc_aggregate_row(
            "Non-Controlled | Acme Holdings LLC"
        )

    def test_noncontrol_with_inc_signal_kept(self):
        """Non-control with ' Inc.' entity signal should NOT be filtered."""
        assert not _is_bdc_aggregate_row(
            "Non-Controlled/Non-Affiliated Investments, Acme Corp Inc. First Lien"
        )

    def test_noncontrol_with_group_signal_kept(self):
        """Non-control with 'group' entity signal should NOT be filtered."""
        assert not _is_bdc_aggregate_row(
            "Non-Controlled | First Lien | Acme Group | Senior Loan"
        )

    def test_noncontrol_without_instrument_signals_filtered(self):
        """Non-control with instrument signals but no entity signals should be filtered.
        'senior secured' and 'term loan' are NOT entity signals."""
        assert _is_bdc_aggregate_row(
            "Non-Controlled/Non-Affiliated Investments of Senior Secured Debt"
        )

    # --- "Investments Investments" parsing artifact (CIK 0001849894) ---
    def test_investments_investments_pattern_filtered(self):
        """'Investments Investments - ...' hierarchy artifact should be filtered."""
        assert _is_bdc_aggregate_row(
            "Investments Investments - non-controlled/non-affiliated "
            "First Lien Debt Capital Equipment"
        )


# ---------------------------------------------------------------------------
# _classify_bdc_asset
# ---------------------------------------------------------------------------

class TestClassifyBdcAsset:
    def test_first_lien_term_loan(self):
        assert _classify_bdc_asset("First Lien Term Loan") == "LOAN"

    def test_second_lien(self):
        assert _classify_bdc_asset("Second Lien Term Loan") == "LOAN"

    def test_promissory_note(self):
        assert _classify_bdc_asset("Subordinated Secured Promissory Note") == "LOAN"

    def test_revolving(self):
        assert _classify_bdc_asset("Senior Secured Revolving Credit Facility") == "LOAN"

    def test_unitranche(self):
        assert _classify_bdc_asset("Unitranche First Lien") == "LOAN"

    def test_delayed_draw(self):
        assert _classify_bdc_asset("Delayed Draw Term Loan") == "LOAN"

    def test_common_stock(self):
        assert _classify_bdc_asset("Common Stock") == "EQUITY_COMMON"

    def test_shares(self):
        assert _classify_bdc_asset("shares") == "EQUITY_COMMON"

    def test_warrant(self):
        assert _classify_bdc_asset("Warrants to purchase common stock") == "EQUITY_COMMON"

    def test_preferred_stock(self):
        assert _classify_bdc_asset("Preferred Stock Series A") == "EQUITY_PREFERRED"

    def test_membership_interest(self):
        assert _classify_bdc_asset("Membership Interest") == "EQUITY_COMMON"

    def test_units(self):
        assert _classify_bdc_asset("Class A Units") == "EQUITY_COMMON"

    def test_series_a(self):
        assert _classify_bdc_asset("Series A Preferred") == "EQUITY_PREFERRED"

    def test_fund(self):
        assert _classify_bdc_asset("Private Credit Fund LP") == "FUND"

    def test_lp_interest(self):
        assert _classify_bdc_asset("LP Interest in Growth Equity Fund") == "FUND"

    def test_limited_partner(self):
        assert _classify_bdc_asset("Limited Partner interest") == "FUND"

    def test_fund_priority_over_equity(self):
        # "fund" should match before equity keywords
        assert _classify_bdc_asset("Fund Units") == "FUND"

    def test_xbrl_axis_override_equity(self):
        assert _classify_bdc_asset("Some Random Text", "Equity Securities") == "EQUITY_COMMON"

    def test_xbrl_axis_override_debt(self):
        assert _classify_bdc_asset("Some Random Text", "First Lien Debt") == "LOAN"

    def test_full_identifier_fallback_loan(self):
        # No instrument_description, but full_identifier has keywords
        assert _classify_bdc_asset("", full_identifier="Acme Corp First Lien Term Loan") == "LOAN"

    def test_full_identifier_fallback_equity(self):
        assert _classify_bdc_asset("", full_identifier="Acme Corp Common Stock") == "EQUITY_COMMON"

    def test_financial_heuristic_rate(self):
        # No keywords anywhere, but has interest_rate -> LOAN
        assert _classify_bdc_asset("", full_identifier="Acme Corp",
                                   has_interest_rate=True) == "LOAN"

    def test_financial_heuristic_shares(self):
        # No keywords anywhere, but has shares -> EQUITY
        assert _classify_bdc_asset("", full_identifier="Acme Corp",
                                   has_shares=True) == "EQUITY_COMMON"

    def test_financial_heuristic_rate_over_shares(self):
        # Both rate and shares -> rate wins (LOAN)
        assert _classify_bdc_asset("", full_identifier="Acme Corp",
                                   has_interest_rate=True,
                                   has_shares=True) == "LOAN"

    # V1 expansion: new heuristics
    def test_heuristic_basis_spread(self):
        assert _classify_bdc_asset("", full_identifier="Acme Corp",
                                   has_basis_spread=True) == "LOAN"

    def test_heuristic_principal_amount(self):
        assert _classify_bdc_asset("", full_identifier="Acme Corp",
                                   has_principal_amount=True) == "LOAN"

    def test_heuristic_spread_over_shares(self):
        # basis_spread wins over shares
        assert _classify_bdc_asset("", full_identifier="Acme Corp",
                                   has_basis_spread=True,
                                   has_shares=True) == "LOAN"

    def test_heuristic_principal_over_shares(self):
        # principal_amount wins over shares
        assert _classify_bdc_asset("", full_identifier="Acme Corp",
                                   has_principal_amount=True,
                                   has_shares=True) == "LOAN"

    # V1 expansion: new keywords
    def test_keyword_senior_secured(self):
        assert _classify_bdc_asset("Senior Secured Debt") == "LOAN"

    def test_keyword_one_stop(self):
        assert _classify_bdc_asset("One stop 4") == "LOAN"

    def test_keyword_equity_interest(self):
        assert _classify_bdc_asset("Equity Interest") == "EQUITY_COMMON"

    def test_keyword_co_investment(self):
        assert _classify_bdc_asset("Co-Investment Vehicle") == "FUND"

    def test_keyword_bridge_loan(self):
        assert _classify_bdc_asset("Bridge Loan") == "LOAN"

    def test_keyword_line_of_credit(self):
        assert _classify_bdc_asset("Line of Credit") == "LOAN"

    def test_keyword_ordinary_shares(self):
        assert _classify_bdc_asset("Ordinary Shares") == "EQUITY_COMMON"

    def test_fallback_other(self):
        assert _classify_bdc_asset("Something completely different") == "OTHER"

    def test_empty_instrument(self):
        assert _classify_bdc_asset("") == "OTHER"

    def test_none_instrument(self):
        assert _classify_bdc_asset(None) == "OTHER"


# ---------------------------------------------------------------------------
# _classify_bdc_issuer
# ---------------------------------------------------------------------------

class TestClassifyBdcIssuer:
    def test_fund_issuer(self):
        assert _classify_bdc_issuer("FUND") == "FUND"

    def test_loan_issuer(self):
        assert _classify_bdc_issuer("LOAN") == "CORPORATE"

    def test_equity_issuer(self):
        assert _classify_bdc_issuer("EQUITY_COMMON") == "CORPORATE"

    def test_other_issuer(self):
        assert _classify_bdc_issuer("OTHER") == "CORPORATE"

    def test_asset_management_equity_is_fund(self):
        """Equity stakes in asset managers should be FUND."""
        assert _classify_bdc_issuer(
            "EQUITY_COMMON", "Ivy Hill Asset Management, L.P., Member interest"
        ) == "FUND"

    def test_asset_management_other_is_fund(self):
        """OTHER-type stakes in asset managers should be FUND."""
        assert _classify_bdc_issuer(
            "OTHER", "Amergin Asset Management, LLC, Class A Units"
        ) == "FUND"

    def test_asset_management_loan_stays_corporate(self):
        """Loans TO asset managers should stay CORPORATE."""
        assert _classify_bdc_issuer(
            "LOAN", "Ivy Hill Asset Management, L.P., Subordinated revolving loan"
        ) == "CORPORATE"

    def test_asset_management_position_guard(self):
        """asset management deep in compound name should not trigger."""
        assert _classify_bdc_issuer(
            "EQUITY_COMMON",
            "Microstar Logistics LLC, Microstar Global Asset Management LLC, Common stock"
        ) == "CORPORATE"

    def test_senior_loan_program_equity_is_fund(self):
        """Equity in lending vehicles should be FUND."""
        assert _classify_bdc_issuer(
            "EQUITY_COMMON", "NMFC Senior Loan Program III LLC, Membership interest"
        ) == "FUND"

    def test_senior_loan_program_debt_stays_corporate(self):
        """Debt positions in lending vehicles stay CORPORATE."""
        assert _classify_bdc_issuer(
            "DEBT", "NMFC Senior Loan Program III LLC, Subordinated Loan"
        ) == "CORPORATE"


# ---------------------------------------------------------------------------
# N-PORT asset/issuer mapping
# ---------------------------------------------------------------------------

class TestNportAssetMapping:
    def test_lon(self):
        assert _classify_nport_asset("LON") == "LOAN"

    def test_dbt(self):
        assert _classify_nport_asset("DBT") == "DEBT"

    def test_ec(self):
        assert _classify_nport_asset("EC") == "EQUITY_COMMON"

    def test_ep(self):
        assert _classify_nport_asset("EP") == "EQUITY_PREFERRED"

    def test_abs(self):
        assert _classify_nport_asset("ABS-MBS") == "OTHER"

    def test_unknown(self):
        assert _classify_nport_asset("XYZ") == "OTHER"

    def test_empty(self):
        assert _classify_nport_asset("") == "OTHER"

    def test_none(self):
        assert _classify_nport_asset(None) == "OTHER"


class TestNportIssuerMapping:
    def test_corp(self):
        assert _classify_nport_issuer("CORP") == "CORPORATE"

    def test_cor(self):
        assert _classify_nport_issuer("COR") == "CORPORATE"

    def test_pf(self):
        assert _classify_nport_issuer("PF") == "FUND"

    def test_rf(self):
        assert _classify_nport_issuer("RF") == "FUND"

    def test_mun(self):
        assert _classify_nport_issuer("MUN") == "GOVERNMENT"

    def test_ust(self):
        assert _classify_nport_issuer("UST") == "GOVERNMENT"

    def test_usga(self):
        assert _classify_nport_issuer("USGA") == "GOVERNMENT"

    def test_nuss(self):
        # NUSS maps to OTHER at function level; GOVERNMENT is name-gated in SQL
        assert _classify_nport_issuer("NUSS") == "OTHER"

    def test_unknown(self):
        assert _classify_nport_issuer("XYZ") == "OTHER"

    def test_empty(self):
        assert _classify_nport_issuer("") == "OTHER"

    def test_none(self):
        assert _classify_nport_issuer(None) == "OTHER"


# ---------------------------------------------------------------------------
# _classify_index
# ---------------------------------------------------------------------------

class TestClassifyIndex:
    def test_direct_lending_loan(self):
        assert _classify_index("LOAN", "CORPORATE", "Acme Corp", "First Lien") == "DIRECT_LENDING"

    def test_direct_lending_debt(self):
        assert _classify_index("DEBT", "CORPORATE", "Acme Corp", "Senior Notes") == "DIRECT_LENDING"

    def test_common_equity(self):
        assert _classify_index("EQUITY_COMMON", "CORPORATE", "Acme Corp", "Common Stock") == "COMMON_EQUITY"

    def test_preferred_equity(self):
        assert _classify_index("EQUITY_PREFERRED", "CORPORATE", "Acme Corp", "Preferred") == "PREFERRED_EQUITY"

    def test_private_credit_fund(self):
        assert _classify_index("FUND", "FUND", "Blue Owl Credit Fund", "") == "PRIVATE_CREDIT_FUND"

    def test_structured_credit_clo(self):
        assert _classify_index("FUND", "FUND", "CLO Holdings", "") == "STRUCTURED_CREDIT"

    def test_private_credit_fund_lending(self):
        assert _classify_index("FUND", "FUND", "Direct Lending Partners", "") == "PRIVATE_CREDIT_FUND"

    def test_private_equity_fund(self):
        assert _classify_index("FUND", "FUND", "Growth Equity Partners", "") == "PRIVATE_EQUITY_FUND"

    def test_private_equity_fund_buyout(self):
        assert _classify_index("FUND", "FUND", "Buyout Fund III", "") == "PRIVATE_EQUITY_FUND"

    def test_private_equity_fund_venture(self):
        assert _classify_index("FUND", "FUND", "Venture Capital Partners", "") == "PRIVATE_EQUITY_FUND"

    def test_fund_no_signals_unclassified(self):
        assert _classify_index("FUND", "FUND", "ABC Partners", "") == "UNCLASSIFIED"

    def test_unclassified_other_asset(self):
        assert _classify_index("OTHER", "CORPORATE", "Acme", "") == "UNCLASSIFIED"

    def test_government_cash(self):
        assert _classify_index("DEBT", "GOVERNMENT", "US Treasury", "") == "CASH"

    def test_ambiguous_fund_credit_wins(self):
        # More credit signals than PE
        result = _classify_index("FUND", "FUND", "Senior Credit Income Fund", "")
        assert result == "PRIVATE_CREDIT_FUND"

    def test_ambiguous_fund_pe_wins(self):
        # More PE signals
        result = _classify_index(
            "FUND", "FUND", "Private Equity Growth Buyout Venture Fund", ""
        )
        assert result == "PRIVATE_EQUITY_FUND"

    def test_loan_with_fund_issuer(self):
        # LOAN + FUND issuer: Direct Lending takes priority over fund classification
        # because asset_category LOAN+CORPORATE check comes first, but FUND issuer
        # means it doesn't match DIRECT_LENDING
        result = _classify_index("LOAN", "FUND", "Credit Fund", "")
        # Not DIRECT_LENDING because issuer is FUND, not CORPORATE
        assert result == "PRIVATE_CREDIT_FUND"


# ---------------------------------------------------------------------------
# _infer_coupon_type
# ---------------------------------------------------------------------------

class TestInferCouponType:
    def test_floating_has_spread(self):
        assert _infer_coupon_type(3.5, 8.0) == "Floating"

    def test_fixed_rate_only(self):
        assert _infer_coupon_type(None, 5.0) == "Fixed"

    def test_fixed_zero_spread(self):
        assert _infer_coupon_type(0, 5.0) == "Fixed"

    def test_blank_nothing(self):
        assert _infer_coupon_type(None, None) == ""

    def test_blank_zeros(self):
        assert _infer_coupon_type(0, 0) == ""

    def test_float_nan_spread(self):
        assert _infer_coupon_type(float("nan"), 5.0) == "Fixed"


# ---------------------------------------------------------------------------
# _is_named_coinvest
# ---------------------------------------------------------------------------

class TestIsNamedCoinvest:
    def test_named_coinvest_inc(self):
        """'Acme, Inc. - Co-Investment' is a named co-invest."""
        assert _is_named_coinvest("Acme, Inc.", "Co-Investment", "Acme, Inc. - Co-Investment")

    def test_named_coinvest_llc(self):
        """'Widget Holdings LLC - Co-Invest' is a named co-invest."""
        assert _is_named_coinvest("Widget Holdings LLC", "Co-Invest", "")

    def test_named_coinvest_corp(self):
        assert _is_named_coinvest("Acme Corp.", "Coinvest Vehicle", "")

    def test_named_coinvest_holdings(self):
        assert _is_named_coinvest("Acme Holdings", "Co-investment", "")

    def test_unnamed_coinvest_rejected(self):
        """Generic 'Co-Investment' with no company marker -> False."""
        assert not _is_named_coinvest("Apollo Co-Investment", "Co-Investment", "")

    def test_unnamed_generic_fund(self):
        """Generic fund with no co-invest keyword -> False."""
        assert not _is_named_coinvest("Blue Owl Credit Fund", "LP Interest", "")

    def test_named_lp_interest_affiliated(self):
        """Named LP interest with affiliated pattern."""
        assert _is_named_coinvest(
            "Acme Holdings LLC",
            "LP Interest",
            "Acme Holdings LLC - LP Interest | Non-Affiliated",
        )

    def test_named_lp_interest_llc_interest(self):
        assert _is_named_coinvest(
            "Widget Group LLC",
            "LLC Interest",
            "Widget Group LLC - LLC Interest | Affiliated",
        )

    def test_no_coinvest_keyword(self):
        """Company marker present but no co-invest/LP pattern -> False."""
        assert not _is_named_coinvest("Acme, Inc.", "Term Loan", "Acme, Inc. - Term Loan")

    def test_empty_issuer(self):
        assert not _is_named_coinvest("", "Co-Investment", "")

    def test_none_issuer(self):
        assert not _is_named_coinvest(None, "Co-Investment", "")

    def test_no_company_marker_with_keyword(self):
        """Co-invest keyword but no company marker -> False."""
        assert not _is_named_coinvest("Some Vehicle", "Co-Investment", "")

    def test_case_insensitive(self):
        """Matching should be case-insensitive."""
        assert _is_named_coinvest("ACME, INC.", "CO-INVESTMENT", "")

    def test_lp_pattern_without_company_marker(self):
        """LP pattern but no company marker -> False."""
        assert not _is_named_coinvest(
            "Some Fund",
            "LP Interest",
            "Some Fund - LP Interest | Non-Affiliated",
        )

    # Path 2: Bare LP interest reclassification
    def test_bare_lp_interest_with_strict_marker(self):
        """'Calabrio, Inc., LP Interest' -> True (operating company co-invest)."""
        assert _is_named_coinvest(
            "Calabrio, Inc., LP Interest", "", "Calabrio, Inc., LP Interest"
        )

    def test_bare_lp_interest_llc(self):
        """'Electrical Source Holdings, LLC, LP Interest' -> True."""
        assert _is_named_coinvest(
            "Electrical Source Holdings, LLC, LP Interest", "",
            "Electrical Source Holdings, LLC, LP Interest",
        )

    def test_bare_lp_interest_corp(self):
        """'BECO Holding Company, Inc., LP Interest' -> True."""
        assert _is_named_coinvest(
            "BECO Holding Company, Inc., LP Interest", "",
            "BECO Holding Company, Inc., LP Interest",
        )

    def test_bare_limited_partnership_interest(self):
        """'Leviathan Holdco, LLC ... Limited partnership interests' -> True."""
        assert _is_named_coinvest(
            "Leviathan Intermediate Holdco, LLC",
            "Limited partnership interests",
            "Leviathan Intermediate Holdco, LLC, Limited partnership interests",
        )

    def test_bare_lp_fund_in_name_stays_fund(self):
        """'Senior Loan Fund LLC, Membership Interest' -> False (genuine fund)."""
        assert not _is_named_coinvest(
            "WHF STRS Ohio Senior Loan Fund LLC",
            "Membership Interest",
            "WHF STRS Ohio Senior Loan Fund LLC, Membership Interest",
        )

    def test_bare_lp_credit_fund_stays_fund(self):
        """'Middle Market Credit Fund II, LLC' -> False (genuine fund)."""
        assert not _is_named_coinvest(
            "Middle Market Credit Fund II, LLC",
            "Member's Interest",
            "Middle Market Credit Fund II, LLC, Member's Interest",
        )

    def test_bare_lp_only_marker_stays_fund(self):
        """'Partnership Capital Growth Investors III, L.P.' -> False (L.P. is not strict)."""
        assert not _is_named_coinvest(
            "Partnership Capital Growth Investors III, L.P.",
            "Limited partnership interest",
            "Partnership Capital Growth Investors III, L.P., Limited partnership interest",
        )

    def test_bare_lp_no_marker_at_all(self):
        """'Majesco, LP Interest 1' -> False (no strict company marker)."""
        assert not _is_named_coinvest(
            "Majesco, LP Interest 1", "", "Majesco, LP Interest 1"
        )


# ---------------------------------------------------------------------------
# _reclassify_named_fund_positions
# ---------------------------------------------------------------------------

class TestReclassifyNamedFundPositions:
    def test_fund_to_equity_common(self):
        """Named co-invest FUND row -> EQUITY_COMMON + CORPORATE."""
        df = pd.DataFrame([{
            "issuer_name": "Acme, Inc.",
            "instrument_description": "Co-Investment",
            "investment_identifier": "Acme, Inc. - Co-Investment",
            "asset_category": "FUND",
            "issuer_category": "FUND",
        }])
        result = _reclassify_named_fund_positions(df)
        assert result.iloc[0]["asset_category"] == "EQUITY_COMMON"
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_fund_to_equity_preferred(self):
        """Named co-invest with 'preferred' -> EQUITY_PREFERRED."""
        df = pd.DataFrame([{
            "issuer_name": "Acme, Inc.",
            "instrument_description": "Co-Investment Preferred",
            "investment_identifier": "Acme, Inc. - Co-Investment Preferred",
            "asset_category": "FUND",
            "issuer_category": "FUND",
        }])
        result = _reclassify_named_fund_positions(df)
        assert result.iloc[0]["asset_category"] == "EQUITY_PREFERRED"
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_unnamed_fund_stays_fund(self):
        """Generic unnamed fund -> stays FUND."""
        df = pd.DataFrame([{
            "issuer_name": "Blue Owl Credit Fund",
            "instrument_description": "LP Interest",
            "investment_identifier": "Blue Owl Credit Fund - LP Interest",
            "asset_category": "FUND",
            "issuer_category": "FUND",
        }])
        result = _reclassify_named_fund_positions(df)
        assert result.iloc[0]["asset_category"] == "FUND"
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_loan_untouched(self):
        """LOAN rows are never reclassified."""
        df = pd.DataFrame([{
            "issuer_name": "Acme, Inc.",
            "instrument_description": "First Lien Term Loan",
            "investment_identifier": "Acme, Inc. - First Lien Term Loan",
            "asset_category": "LOAN",
            "issuer_category": "CORPORATE",
        }])
        result = _reclassify_named_fund_positions(df)
        assert result.iloc[0]["asset_category"] == "LOAN"

    def test_equity_untouched(self):
        """EQUITY rows are never reclassified."""
        df = pd.DataFrame([{
            "issuer_name": "Acme, Inc.",
            "instrument_description": "Common Stock",
            "investment_identifier": "Acme, Inc. - Common Stock",
            "asset_category": "EQUITY_COMMON",
            "issuer_category": "CORPORATE",
        }])
        result = _reclassify_named_fund_positions(df)
        assert result.iloc[0]["asset_category"] == "EQUITY_COMMON"

    def test_empty_df(self):
        """Empty DataFrame returns empty."""
        df = pd.DataFrame(columns=["asset_category", "issuer_name",
                                    "instrument_description"])
        result = _reclassify_named_fund_positions(df)
        assert len(result) == 0

    def test_mixed_df(self):
        """Mixed DataFrame: only FUND + named co-invest rows get reclassified."""
        df = pd.DataFrame([
            {
                "issuer_name": "Acme, Inc.",
                "instrument_description": "Co-Investment",
                "investment_identifier": "Acme, Inc. - Co-Investment",
                "asset_category": "FUND",
                "issuer_category": "FUND",
            },
            {
                "issuer_name": "Growth Equity Partners",
                "instrument_description": "LP Interest",
                "investment_identifier": "Growth Equity Partners - LP Interest",
                "asset_category": "FUND",
                "issuer_category": "FUND",
            },
            {
                "issuer_name": "Widget Corp.",
                "instrument_description": "Term Loan",
                "investment_identifier": "Widget Corp. - Term Loan",
                "asset_category": "LOAN",
                "issuer_category": "CORPORATE",
            },
        ])
        result = _reclassify_named_fund_positions(df)
        # Acme -> EQUITY_COMMON (named co-invest)
        assert result.iloc[0]["asset_category"] == "EQUITY_COMMON"
        assert result.iloc[0]["issuer_category"] == "CORPORATE"
        # Growth Equity Partners -> stays FUND (no company marker)
        assert result.iloc[1]["asset_category"] == "FUND"
        assert result.iloc[1]["issuer_category"] == "FUND"
        # Widget Corp -> stays LOAN
        assert result.iloc[2]["asset_category"] == "LOAN"

    def test_bdc_investment_identifier_column(self):
        """Uses bdc_investment_identifier when investment_identifier is absent."""
        df = pd.DataFrame([{
            "issuer_name": "Acme Holdings LLC",
            "instrument_description": "LP Interest",
            "bdc_investment_identifier": "Acme Holdings LLC - LP Interest | Non-Affiliated",
            "asset_category": "FUND",
            "issuer_category": "FUND",
        }])
        result = _reclassify_named_fund_positions(df)
        assert result.iloc[0]["asset_category"] == "EQUITY_COMMON"
        assert result.iloc[0]["issuer_category"] == "CORPORATE"


# ---------------------------------------------------------------------------
# _prepare_bdc
# ---------------------------------------------------------------------------

class TestPrepareBdc:
    def _make_bdc_df(self, rows):
        """Helper to create a minimal BDC DataFrame."""
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_filters_aggregate_rows(self):
        df = self._make_bdc_df([
            {"investment_identifier": "Non-Control/Non-Affiliate Investments - Net assets",
             "cik": "123", "fair_value": 5000000},
            {"investment_identifier": "Caitec, Inc. - Term Loan",
             "cik": "123", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Caitec, Inc."

    def test_keeps_non_prefix_names(self):
        """Non-prefix bare issuer names are kept as individual holdings."""
        df = self._make_bdc_df([
            {"investment_identifier": "Caitec, Inc.", "cik": "123",
             "interest_rate": 8.5, "fair_value": 500000},
            {"investment_identifier": "Acme Corp - Term Loan", "cik": "123",
             "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2

    def test_prefix_subtotal_removed(self):
        """Short identifier that is a prefix of a longer one is a subtotal."""
        df = self._make_bdc_df([
            {"investment_identifier": "Medallia, Inc.", "cik": "123",
             "accession_number": "001", "interest_rate": 11.0,
             "fair_value": 1000000},
            {"investment_identifier": "Medallia, Inc., Emerald JV LP",
             "cik": "123", "accession_number": "001",
             "interest_rate": 11.0, "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert "Emerald" in result.iloc[0]["bdc_investment_identifier"]

    def test_prefix_subtotal_keeps_child(self):
        """Prefix filter keeps the longer child, removes the shorter parent."""
        df = self._make_bdc_df([
            {"investment_identifier": "Kaseya Inc., First Lien", "cik": "456",
             "accession_number": "002", "basis_spread": 0.035,
             "fair_value": 63000000},
            {"investment_identifier": "Kaseya Inc., First Lien - Drawn 1",
             "cik": "456", "accession_number": "002", "basis_spread": 0.035,
             "fair_value": 50000000},
            {"investment_identifier": "Kaseya Inc., First Lien - Undrawn 1",
             "cik": "456", "accession_number": "002",
             "fair_value": 13000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        ids = result["bdc_investment_identifier"].tolist()
        assert all("Drawn" in i or "Undrawn" in i for i in ids)

    def test_bare_name_classified_by_rate(self):
        """Bare names with interest_rate are classified as LOAN via heuristic."""
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp", "cik": "123",
             "fair_value": 1000000, "interest_rate": 8.5, "basis_spread": 3.0},
        ])
        result = _prepare_bdc(df)
        assert result.iloc[0]["asset_category"] == "LOAN"
        assert result.iloc[0]["issuer_name"] == "Acme Corp"
        assert result.iloc[0]["instrument_description"] == ""

    def test_bare_name_classified_by_shares(self):
        """Bare names with shares_held are classified as EQUITY_COMMON."""
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp", "cik": "123",
             "fair_value": 500000, "shares_held": 50000},
        ])
        result = _prepare_bdc(df)
        assert result.iloc[0]["asset_category"] == "EQUITY_COMMON"

    def test_column_mapping(self):
        df = self._make_bdc_df([
            {
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "cik": "42",
                "entity_name": "Test BDC",
                "fair_value": 1000000,
                "interest_rate": 8.5,
                "basis_spread": 3.5,
            },
        ])
        result = _prepare_bdc(df)
        assert result.iloc[0]["source"] == "bdc"
        assert result.iloc[0]["cik"] == "0000000042"
        assert result.iloc[0]["entity_name"] == "Test BDC"
        assert result.iloc[0]["asset_category"] == "LOAN"
        assert result.iloc[0]["issuer_category"] == "CORPORATE"
        assert result.iloc[0]["coupon_type"] == "Floating"

    def test_filters_xbrl_artifacts_no_financial_data(self):
        """Rows with no fair_value/rate/principal/shares are XBRL artifacts."""
        df = self._make_bdc_df([
            # Artifact: no financial data at all
            {"investment_identifier": "Section Header", "cik": "123",
             "fair_value": None, "interest_rate": None, "principal_amount": None,
             "shares_held": None},
            # Real holding: has fair_value
            {"investment_identifier": "Real Corp - Term Loan", "cik": "123",
             "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Real Corp"

    def test_filters_row_with_interest_rate_only_no_fv(self):
        """Rows with interest_rate but no fair_value are filtered (C101)."""
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp", "cik": "123",
             "fair_value": None, "interest_rate": 8.5},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 0

    def test_has_all_unified_columns(self):
        df = self._make_bdc_df([
            {"investment_identifier": "X - Term Loan", "cik": "1"},
        ])
        result = _prepare_bdc(df)
        for col in UNIFIED_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"

    def test_named_coinvest_reclassified(self):
        """Named co-invest: Acme, Inc. - Co-Investment -> EQUITY_COMMON + CORPORATE."""
        df = self._make_bdc_df([
            {"investment_identifier": "Acme, Inc. - Co-Investment",
             "cik": "123", "fair_value": 5000000},
        ])
        result = _prepare_bdc(df)
        assert result.iloc[0]["asset_category"] == "EQUITY_COMMON"
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_unnamed_fund_stays_fund(self):
        """Unnamed fund LP stays as FUND."""
        df = self._make_bdc_df([
            {"investment_identifier": "Growth Equity Partners - LP Interest",
             "cik": "123", "fair_value": 2000000},
        ])
        result = _prepare_bdc(df)
        assert result.iloc[0]["asset_category"] == "FUND"
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_bare_lp_interest_reclassified_via_sql(self):
        """'Calabrio, Inc., LP Interest' -> EQUITY_COMMON via SQL path."""
        df = self._make_bdc_df([
            {"investment_identifier": "Calabrio, Inc., LP Interest",
             "cik": "123", "fair_value": 782000},
        ])
        result = _prepare_bdc(df)
        assert result.iloc[0]["asset_category"] == "EQUITY_COMMON"
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_fund_with_llc_stays_fund_via_sql(self):
        """'Senior Loan Fund LLC Equity' stays as FUND (has 'fund' word)."""
        df = self._make_bdc_df([
            {"investment_identifier": "WHF STRS Ohio Senior Loan Fund LLC Equity",
             "cik": "123", "fair_value": 5000000},
        ])
        result = _prepare_bdc(df)
        assert result.iloc[0]["asset_category"] == "FUND"
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_long_noncontrol_dimension_path_survives(self):
        """Long dimension-path identifier (>=150 chars) with 'non-controlled' survives _prepare_bdc.

        The affiliation prefix is stripped from _raw_id (CTE 1c), so
        bdc_investment_identifier loses the prefix but the row is kept.
        """
        long_id = (
            "Non-Controlled/Non-Affiliated Investments Senior Secured First Lien Loans "
            "Industry Commercial Services & Supplies Company Advanced Web Technologies "
            "Holding Company Delayed Draw SOFR Spread 5.75"
        )
        stripped_id = (
            "Senior Secured First Lien Loans "
            "Industry Commercial Services & Supplies Company Advanced Web Technologies "
            "Holding Company Delayed Draw SOFR Spread 5.75"
        )
        df = self._make_bdc_df([
            {"investment_identifier": long_id,
             "cik": "123", "fair_value": 5000000,
             "interest_rate": 10.5, "basis_spread": 5.0},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["bdc_investment_identifier"] == stripped_id


# ---------------------------------------------------------------------------
# Amendment dedup in _prepare_bdc (CTE 1b)
# ---------------------------------------------------------------------------

class TestAmendmentDedup:
    """Test that _prepare_bdc keeps only the latest filing per CIK+report_date+form_family."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation", "period",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_amendment_with_holdings_supersedes_original(self):
        """When both 10-K and 10-K/A have holdings, amendment's rows are kept."""
        df = self._make_bdc_df([
            # Original 10-K
            {"cik": "100", "accession_number": "acc-orig", "form_type": "10-K",
             "filing_date": "2024-02-28", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Acme Corp - Term Loan",
             "fair_value": "1000000"},
            # Amendment 10-K/A with corrected FV
            {"cik": "100", "accession_number": "acc-amend", "form_type": "10-K/A",
             "filing_date": "2024-05-15", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Acme Corp - Term Loan",
             "fair_value": "1050000"},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert float(result.iloc[0]["fair_value"]) == 1050000.0

    def test_amendment_with_no_holdings_keeps_original(self):
        """When 10-K/A has no XBRL holdings, original 10-K rows survive."""
        df = self._make_bdc_df([
            # Original 10-K with holdings
            {"cik": "200", "accession_number": "acc-orig", "form_type": "10-K",
             "filing_date": "2024-02-28", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Beta Inc. - Senior Secured",
             "fair_value": "5000000"},
            {"cik": "200", "accession_number": "acc-orig", "form_type": "10-K",
             "filing_date": "2024-02-28", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Gamma LLC - Equity",
             "fair_value": "2000000", "shares_held": "10000"},
            # No rows from 10-K/A (it had no XBRL investment data)
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2  # Both original rows preserved

    def test_multiple_amendments_keeps_latest(self):
        """Three amendments: only the latest-filed accession's rows survive."""
        df = self._make_bdc_df([
            {"cik": "300", "accession_number": "acc-orig", "form_type": "10-K",
             "filing_date": "2024-02-28", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Acme - Loan", "fair_value": "100"},
            {"cik": "300", "accession_number": "acc-a1", "form_type": "10-K/A",
             "filing_date": "2024-03-24", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Acme - Loan", "fair_value": "200"},
            {"cik": "300", "accession_number": "acc-a2", "form_type": "10-K/A",
             "filing_date": "2024-07-07", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Acme - Loan", "fair_value": "300"},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert float(result.iloc[0]["fair_value"]) == 300.0

    def test_cross_form_family_independent(self):
        """10-K/A only affects 10-K, not 10-Q for the same report_date."""
        df = self._make_bdc_df([
            # 10-K original (will be superseded)
            {"cik": "400", "accession_number": "acc-k-orig", "form_type": "10-K",
             "filing_date": "2024-02-28", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Alpha - Loan", "fair_value": "100"},
            # 10-K/A amendment (supersedes 10-K)
            {"cik": "400", "accession_number": "acc-k-amend", "form_type": "10-K/A",
             "filing_date": "2024-05-15", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Alpha - Loan", "fair_value": "150"},
            # 10-Q for same report_date (different form family, unaffected)
            {"cik": "400", "accession_number": "acc-q", "form_type": "10-Q",
             "filing_date": "2024-02-10", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Alpha - Loan", "fair_value": "100"},
        ])
        result = _prepare_bdc(df)
        # 10-K/A row + 10-Q row = 2 (original 10-K dropped)
        assert len(result) == 2
        accs = set(result["accession_number"].tolist())
        assert "acc-k-orig" not in accs
        assert "acc-k-amend" in accs
        assert "acc-q" in accs

    def test_different_ciks_independent(self):
        """Amendment dedup is scoped per CIK -- other CIKs unaffected."""
        df = self._make_bdc_df([
            {"cik": "500", "accession_number": "acc-a-orig", "form_type": "10-K",
             "filing_date": "2024-02-28", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Foo - Loan", "fair_value": "100"},
            {"cik": "500", "accession_number": "acc-a-amend", "form_type": "10-K/A",
             "filing_date": "2024-05-15", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Foo - Loan", "fair_value": "200"},
            {"cik": "600", "accession_number": "acc-b", "form_type": "10-K",
             "filing_date": "2024-03-01", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Bar - Loan", "fair_value": "500"},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        cik500 = result[result["cik"] == "0000000500"]
        assert len(cik500) == 1
        assert float(cik500.iloc[0]["fair_value"]) == 200.0
        cik600 = result[result["cik"] == "0000000600"]
        assert len(cik600) == 1
        assert float(cik600.iloc[0]["fair_value"]) == 500.0

    def test_orphan_amendment_kept(self):
        """10-K/A with no matching 10-K original is kept."""
        df = self._make_bdc_df([
            {"cik": "700", "accession_number": "acc-orphan", "form_type": "10-K/A",
             "filing_date": "2024-05-15", "report_date": "2023-12-31",
             "period": "2023-12-31",
             "investment_identifier": "Delta - Loan", "fair_value": "1000000"},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1

    def test_10q_amendment_dedup(self):
        """10-Q/A supersedes 10-Q for the same CIK+report_date."""
        df = self._make_bdc_df([
            {"cik": "800", "accession_number": "acc-q-orig", "form_type": "10-Q",
             "filing_date": "2024-05-10", "report_date": "2024-03-31",
             "period": "2024-03-31",
             "investment_identifier": "Zeta Corp - Loan", "fair_value": "100"},
            {"cik": "800", "accession_number": "acc-q-amend", "form_type": "10-Q/A",
             "filing_date": "2024-06-01", "report_date": "2024-03-31",
             "period": "2024-03-31",
             "investment_identifier": "Zeta Corp - Loan", "fair_value": "110"},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert float(result.iloc[0]["fair_value"]) == 110.0


# ---------------------------------------------------------------------------
# _prepare_nport
# ---------------------------------------------------------------------------

class TestPrepareNport:
    def _make_nport_df(self, rows):
        """Helper to create a minimal N-PORT DataFrame."""
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row["currency_value"] = 1000000
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_level_3_filter(self):
        df = self._make_nport_df([
            {"fair_value_level": "1", "cik": "100", "asset_cat": "DBT",
             "issuer_type": "CORP", "currency_value": 1000000},
            {"fair_value_level": "2", "cik": "100", "asset_cat": "DBT",
             "issuer_type": "CORP", "currency_value": 2000000},
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "currency_value": 3000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1
        assert result.iloc[0]["asset_category"] == "LOAN"

    def test_column_mapping(self):
        df = self._make_nport_df([
            {
                "fair_value_level": "3",
                "cik": "200",
                "registrant_name": "Test Fund",
                "issuer_name": "Private Co",
                "issuer_title": "Senior Secured Note",
                "asset_cat": "LON",
                "issuer_type": "CORP",
                "currency_value": 5000000,
                "annualized_rate": 7.5,
                "coupon_type": "Floating",
            },
        ])
        result = _prepare_nport(df)
        assert result.iloc[0]["source"] == "nport"
        assert result.iloc[0]["entity_name"] == "Test Fund"
        assert result.iloc[0]["issuer_name"] == "Private Co"
        assert result.iloc[0]["asset_category"] == "LOAN"
        assert result.iloc[0]["issuer_category"] == "CORPORATE"
        assert result.iloc[0]["fair_value_level"] == "3"

    def test_empty_after_filter(self):
        df = self._make_nport_df([
            {"fair_value_level": "1", "cik": "100", "asset_cat": "DBT",
             "issuer_type": "CORP"},
        ])
        result = _prepare_nport(df)
        assert len(result) == 0
        assert list(result.columns) == UNIFIED_COLUMNS

    def test_has_all_unified_columns(self):
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "1", "asset_cat": "LON",
             "issuer_type": "CORP"},
        ])
        result = _prepare_nport(df)
        for col in UNIFIED_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"

    # V1 expansion: LON/DBT + OTHER issuer defaults to CORPORATE
    def test_lon_other_issuer_defaults_corporate(self):
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "OTHER"},
        ])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "CORPORATE"
        assert result.iloc[0]["index_classification"] == ""  # set later by caller

    def test_dbt_blank_issuer_defaults_corporate(self):
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "DBT",
             "issuer_type": ""},
        ])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_equity_other_issuer_stays_other(self):
        """EC + OTHER issuer should NOT be reclassified."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "EC",
             "issuer_type": "OTHER"},
        ])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "OTHER"

    # N-PORT balance/unit mapping tests

    def test_balance_pa_maps_to_principal_amount(self):
        """unit=PA -> principal_amount populated, shares_held NULL."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100", "asset_cat": "LON",
            "issuer_type": "CORP", "balance": 5000, "unit": "PA",
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["principal_amount"] == 5000.0
        assert pd.isna(result.iloc[0]["shares_held"])

    def test_balance_ns_maps_to_shares_held(self):
        """unit=NS -> shares_held populated, principal_amount NULL."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100", "asset_cat": "EC",
            "issuer_type": "CORP", "balance": 10000, "unit": "NS",
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["shares_held"] == 10000.0
        assert pd.isna(result.iloc[0]["principal_amount"])

    def test_balance_ou_maps_to_null(self):
        """unit=OU -> both shares_held and principal_amount NULL."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100", "asset_cat": "EC",
            "issuer_type": "CORP", "balance": 100, "unit": "OU",
        }])
        result = _prepare_nport(df)
        assert pd.isna(result.iloc[0]["principal_amount"])
        assert pd.isna(result.iloc[0]["shares_held"])

    def test_balance_nc_maps_to_null(self):
        """unit=NC (contracts) -> both NULL."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100", "asset_cat": "LON",
            "issuer_type": "CORP", "balance": 5, "unit": "NC",
        }])
        result = _prepare_nport(df)
        assert pd.isna(result.iloc[0]["principal_amount"])
        assert pd.isna(result.iloc[0]["shares_held"])

    def test_balance_null_with_pa_unit(self):
        """unit=PA but balance=NULL -> principal_amount NULL."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100", "asset_cat": "LON",
            "issuer_type": "CORP", "balance": None, "unit": "PA",
        }])
        result = _prepare_nport(df)
        assert pd.isna(result.iloc[0]["principal_amount"])

    def test_schema_has_shares_held_not_bdc_shares_held(self):
        """Unified schema includes shares_held, not bdc_shares_held."""
        assert "shares_held" in UNIFIED_COLUMNS
        assert "bdc_shares_held" not in UNIFIED_COLUMNS

    def test_bdc_shares_still_maps_to_shares_held(self):
        """BDC rows still populate shares_held from shares_held input."""
        bdc_cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        row = {c: "" for c in bdc_cols}
        row.update({
            "investment_identifier": "Acme Corp - Common Stock",
            "cik": "123", "fair_value": 500000, "shares_held": 5000,
        })
        bdc_df = pd.DataFrame([row])
        result = _prepare_bdc(bdc_df)
        assert result.iloc[0]["shares_held"] == 5000.0

    def test_nport_and_bdc_same_column_count(self):
        """Both BDC and N-PORT prepare functions produce same column set."""
        bdc_cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        bdc_row = {c: "" for c in bdc_cols}
        bdc_row.update({
            "investment_identifier": "X - Term Loan", "cik": "1",
        })
        bdc_result = _prepare_bdc(pd.DataFrame([bdc_row]))

        nport_df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "1", "asset_cat": "LON",
            "issuer_type": "CORP",
        }])
        nport_result = _prepare_nport(nport_df)

        assert set(bdc_result.columns) == set(nport_result.columns)


# ---------------------------------------------------------------------------
# Text enrichment: reference_rate_type and maturity_date from identifier
# ---------------------------------------------------------------------------

class TestTextEnrichment:
    """Tests for BDC text-based enrichment of reference_rate_type and maturity_date."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    # -- reference_rate_type --

    def test_sofr_extracted(self):
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - First Lien - SOFR+550",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["reference_rate_type"] == "SOFR"

    def test_libor_extracted(self):
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan L+625, 1.00% Floor",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        # "L+" doesn't contain "libor" as a word, so no match
        assert result.iloc[0]["reference_rate_type"] == ""

    def test_libor_word_extracted(self):
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan LIBOR+300",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["reference_rate_type"] == "LIBOR"

    def test_prime_extracted(self):
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Revolver Prime+200",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["reference_rate_type"] == "PRIME"

    def test_no_ref_rate_in_text(self):
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["reference_rate_type"] == ""

    def test_structured_ref_rate_takes_priority(self):
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - SOFR+500",
            "cik": "1", "fair_value": 1000000,
            "reference_rate_type": "PRIME",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["reference_rate_type"] == "PRIME"

    # -- maturity_date --

    def test_maturity_date_after_date(self):
        """Pattern: '8/28/2025 Maturity'"""
        df = self._make_bdc_df([{
            "investment_identifier":
                "Acme Corp, First Lien Debt, 8/28/2025 Maturity",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == "2025-08-28"

    def test_due_date_pattern(self):
        """Pattern: 'Due 5/12/28'"""
        df = self._make_bdc_df([{
            "investment_identifier":
                "Golden Source, Senior Secured Term Loan, Due 5/12/28",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == "2028-05-12"

    def test_maturity_date_label_pattern(self):
        """Pattern: 'Maturity Date 03/24/2028'"""
        df = self._make_bdc_df([{
            "investment_identifier":
                "Acme Corp First Lien Debt SOFR+500 Maturity Date 03/24/2028",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == "2028-03-24"

    def test_maturity_word_before_date(self):
        """Pattern: 'Maturity 10/28/2028'"""
        df = self._make_bdc_df([{
            "investment_identifier":
                "Issuer Name NBH Group Maturity 10/28/2028 Industry Healthcare",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == "2028-10-28"

    def test_acquisition_date_not_extracted(self):
        """Acquisition Date should NOT be treated as maturity."""
        df = self._make_bdc_df([{
            "investment_identifier":
                "Warrant, Acquisition Date 12/23/2022, Common Stock",
            "cik": "1", "fair_value": 50000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == ""

    def test_structured_maturity_takes_priority(self):
        df = self._make_bdc_df([{
            "investment_identifier":
                "Acme Corp, First Lien Debt, 8/28/2025 Maturity",
            "cik": "1", "fair_value": 1000000,
            "maturity_date": "2025-12-31",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == "2025-12-31"

    def test_two_digit_year_parsed(self):
        """'Due 11/1/25' -> 2025-11-01"""
        df = self._make_bdc_df([{
            "investment_identifier":
                "Controlled Affiliates, Senior Note, 12%, due 11/1/25",
            "cik": "1", "fair_value": 500000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == "2025-11-01"

    # -- C402: maturity date guard (reject pre-1950 dates) ----------------

    def test_maturity_date_3digit_year_rejected(self):
        """3-digit year typo '6/28/225' should be rejected (C402 Bug A)."""
        df = self._make_bdc_df([{
            "investment_identifier":
                "Acme Corp, First Lien Debt, Due 6/28/225",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == ""

    def test_maturity_date_1899_sentinel_rejected(self):
        """Filer sentinel date 1899-12-31 should be rejected (C402 Bug B)."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp, Equity",
            "cik": "1", "fair_value": 500000,
            "maturity_date": "1899-12-31",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == ""

    def test_maturity_date_valid_passes_guard(self):
        """Normal maturity dates should pass through the guard."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp, First Lien Debt",
            "cik": "1", "fair_value": 1000000,
            "maturity_date": "2028-06-30",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == "2028-06-30"

    def test_maturity_date_year_0225_from_text_rejected(self):
        """Text-extracted date parsing to year 0225 should be rejected."""
        df = self._make_bdc_df([{
            "investment_identifier":
                "Acme Corp, Senior Note, Due 6/28/225",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == ""

    # -- C101: null fair_value rows filtered ----------------------------

    def test_null_fv_row_filtered(self):
        """Rows with NULL fair_value are excluded (C101)."""
        df = self._make_bdc_df([
            {"investment_identifier": "Unfunded Revolver - Acme Corp",
             "cik": "1", "fair_value": None, "principal_amount": 5000000},
            {"investment_identifier": "Real Corp - Term Loan",
             "cik": "1", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Real Corp"

    def test_null_fv_with_shares_filtered(self):
        """Even rows with shares but no FV should be excluded."""
        df = self._make_bdc_df([
            {"investment_identifier": "Warrant - Acme Corp",
             "cik": "1", "fair_value": None, "shares_held": 100},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 0

    def test_zero_fv_row_kept(self):
        """Rows with fair_value=0 are NOT filtered (different from NULL)."""
        df = self._make_bdc_df([
            {"investment_identifier": "Written Off - Acme Corp",
             "cik": "1", "fair_value": 0, "cost": 500000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# build_unified_holdings (integration)
# ---------------------------------------------------------------------------

class TestBuildUnifiedHoldings:
    def _make_bdc_df(self):
        return pd.DataFrame([
            {
                "cik": "123", "entity_name": "Test BDC",
                "accession_number": "0001-23", "form_type": "10-K",
                "filing_date": "2023-06-01", "report_date": "2023-03-31",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "fair_value": 1000000.0, "cost": 990000.0,
                "principal_amount": 1000000.0, "interest_rate": 8.5,
                "basis_spread": 3.5, "reference_rate_type": "SOFR",
                "maturity_date": "2028-01-15", "pct_of_net_assets": 0.05,
                "pik_rate": None, "shares_held": None,
                "unrealized_gain_loss": 10000.0, "dimensions_raw": "x=y",
                "investment_type": "", "industry": "", "affiliation": "",
                "period": "2023-03-31",
            },
            {
                "cik": "123", "entity_name": "Test BDC",
                "accession_number": "0001-23", "form_type": "10-K",
                "filing_date": "2023-06-01", "report_date": "2023-03-31",
                "investment_identifier": "Growth Fund LP - LP Interest",
                "fair_value": 500000.0, "cost": 450000.0,
                "principal_amount": None, "interest_rate": None,
                "basis_spread": None, "reference_rate_type": "",
                "maturity_date": "", "pct_of_net_assets": 0.025,
                "pik_rate": None, "shares_held": None,
                "unrealized_gain_loss": 50000.0, "dimensions_raw": "x=y",
                "investment_type": "", "industry": "", "affiliation": "",
                "period": "2023-03-31",
            },
            # Aggregate row -- should be filtered out
            {
                "cik": "123", "entity_name": "Test BDC",
                "accession_number": "0001-23", "form_type": "10-K",
                "filing_date": "2023-06-01", "report_date": "2023-03-31",
                "investment_identifier": "Total Investments",
                "fair_value": 1500000.0, "cost": None,
                "principal_amount": None, "interest_rate": None,
                "basis_spread": None, "reference_rate_type": "",
                "maturity_date": "", "pct_of_net_assets": 1.0,
                "pik_rate": None, "shares_held": None,
                "unrealized_gain_loss": None, "dimensions_raw": "",
                "investment_type": "", "industry": "", "affiliation": "",
                "period": "2023-03-31",
            },
        ])

    def _make_nport_df(self):
        return pd.DataFrame([
            {
                "accession_number": "0002-45", "holding_id": "H001",
                "issuer_name": "Private Borrower LLC",
                "issuer_lei": "LEI123", "issuer_title": "Senior Secured Loan",
                "issuer_cusip": "ABC123", "currency_value": 2000000.0,
                "percentage": 0.03, "asset_cat": "LON", "issuer_type": "CORP",
                "investment_country": "US", "is_restricted_security": "Y",
                "fair_value_level": 3, "maturity_date": "2027-06-15",
                "coupon_type": "Floating", "annualized_rate": 9.0,
                "identifier_isin": "US_ISIN_1", "identifier_ticker": "",
                "payoff_profile": "Long", "cik": "456",
                "registrant_name": "Test Interval Fund",
                "filing_date": "2023-07-15", "report_date": "2023-06-30",
                "series_name": "Test Series", "series_id": "S001",
                "quarter": "2023q2", "balance": 2000000, "unit": "PA",
                "other_unit_desc": "", "exchange_rate": None,
                "other_asset": "", "other_issuer": "", "sub_type": "",
                "derivative_cat": "", "is_default": "N",
                "other_identifier": "", "currency_code": "USD",
            },
            # Level 1 row -- should be filtered out
            {
                "accession_number": "0002-45", "holding_id": "H002",
                "issuer_name": "Public Stock",
                "issuer_lei": "", "issuer_title": "Common Stock",
                "issuer_cusip": "XYZ789", "currency_value": 500000.0,
                "percentage": 0.01, "asset_cat": "EC", "issuer_type": "CORP",
                "investment_country": "US", "is_restricted_security": "N",
                "fair_value_level": 1, "maturity_date": "",
                "coupon_type": "", "annualized_rate": 0,
                "identifier_isin": "", "identifier_ticker": "PUB",
                "payoff_profile": "Long", "cik": "456",
                "registrant_name": "Test Interval Fund",
                "filing_date": "2023-07-15", "report_date": "2023-06-30",
                "series_name": "Test Series", "series_id": "S001",
                "quarter": "2023q2", "balance": 1000, "unit": "NS",
                "other_unit_desc": "", "exchange_rate": None,
                "other_asset": "", "other_issuer": "", "sub_type": "",
                "derivative_cat": "", "is_default": "N",
                "other_identifier": "", "currency_code": "USD",
            },
        ])

    def test_full_integration(self, tmp_path):
        """End-to-end test with in-memory DataFrames."""
        bdc_df = self._make_bdc_df()
        nport_df = self._make_nport_df()

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test_output.csv"):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

        # 2 BDC (Acme Corp + Growth Fund) + 1 N-PORT (Private Borrower) = 3
        assert len(result) == 3

        # Check column count matches schema
        assert list(result.columns) == UNIFIED_COLUMNS

        # Verify BDC aggregate was filtered
        assert not result["issuer_name"].str.contains("Total Investments").any()

        # Verify N-PORT Level 1 was filtered
        assert not result["issuer_name"].str.contains("Public Stock").any()

        # Check index classification
        acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert acme["index_classification"] == "DIRECT_LENDING"
        assert acme["asset_category"] == "LOAN"
        assert acme["coupon_type"] == "Floating"

        borrower = result[result["issuer_name"] == "Private Borrower LLC"].iloc[0]
        assert borrower["index_classification"] == "DIRECT_LENDING"
        assert borrower["source"] == "nport"

        # Output file should exist
        assert (tmp_path / "test_output.csv").exists()

    def test_load_from_disk(self, tmp_path):
        """Test loading from CSV files."""
        bdc_df = self._make_bdc_df()
        nport_df = self._make_nport_df()

        bdc_path = tmp_path / "bdc.csv"
        nport_path = tmp_path / "nport.csv"
        output_path = tmp_path / "unified.csv"

        bdc_df.to_csv(bdc_path, index=False)
        nport_df.to_csv(nport_path, index=False)

        with patch("pipeline.unified_holdings.BDC_HOLDINGS_FILE", bdc_path), \
             patch("pipeline.unified_holdings.NPORT_HOLDINGS_FILE", nport_path), \
             patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE", output_path):
            result = build_unified_holdings()

        assert len(result) == 3
        assert output_path.exists()


# ---------------------------------------------------------------------------
# Entity enrichment in build_unified_holdings
# ---------------------------------------------------------------------------

class TestEntityEnrichment:
    """Tests for entity_id population via entity_lookup join."""

    def _make_bdc_df(self):
        return pd.DataFrame([{
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "fair_value": 1000000.0, "cost": 990000.0,
            "principal_amount": 1000000.0, "interest_rate": 8.5,
            "basis_spread": 3.5, "reference_rate_type": "SOFR",
            "maturity_date": "2028-01-15", "pct_of_net_assets": 0.05,
            "pik_rate": None, "shares_held": None,
            "unrealized_gain_loss": 10000.0, "dimensions_raw": "x=y",
            "investment_type": "", "industry": "", "affiliation": "",
            "period": "2023-03-31",
        }])

    def _make_nport_df(self):
        return pd.DataFrame(columns=[
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit", "other_unit_desc", "exchange_rate",
            "other_asset", "other_issuer", "sub_type", "derivative_cat",
            "is_default", "other_identifier", "currency_code",
        ])

    def test_entity_id_populated_when_lookup_exists(self, tmp_path):
        """When entity_lookup.csv exists, entity_id should be populated."""
        bdc_df = self._make_bdc_df()
        nport_df = self._make_nport_df()

        # Create entity lookup with matching issuer_name variant
        lookup_path = tmp_path / "entity_lookup.csv"
        lookup_df = pd.DataFrame([{
            "entity_id": "ENT-00000001",
            "canonical_name": "Acme Corporation",
            "normalized_name": "acme corp",
            "issuer_name_variant": "Acme Corp",
            "source": "bdc",
            "occurrence_count": 10,
            "cluster_method": "exact",
            "cusip": "",
            "lei": "",
        }])
        lookup_df.to_csv(lookup_path, index=False)

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "output.csv"), \
             patch("pipeline.unified_holdings.ENTITY_LOOKUP_FILE",
                    lookup_path):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

        acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert acme["entity_id"] == "ENT-00000001"
        assert acme["canonical_name"] == "Acme Corporation"

    def test_entity_id_empty_when_no_lookup(self, tmp_path):
        """When entity_lookup.csv does not exist, entity_id stays empty."""
        bdc_df = self._make_bdc_df()
        nport_df = self._make_nport_df()

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "output.csv"), \
             patch("pipeline.unified_holdings.ENTITY_LOOKUP_FILE",
                    tmp_path / "nonexistent_lookup.csv"):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

        assert (result["entity_id"] == "").all()
        assert (result["canonical_name"] == "").all()

    def test_unmatched_rows_get_empty_entity_id(self, tmp_path):
        """Rows not in entity_lookup get empty entity_id (not NULL)."""
        bdc_df = self._make_bdc_df()
        nport_df = self._make_nport_df()

        # Lookup has a different issuer name
        lookup_path = tmp_path / "entity_lookup.csv"
        lookup_df = pd.DataFrame([{
            "entity_id": "ENT-00000099",
            "canonical_name": "Other Corp",
            "normalized_name": "other corp",
            "issuer_name_variant": "Other Corp",
            "source": "bdc",
            "occurrence_count": 5,
            "cluster_method": "exact",
            "cusip": "",
            "lei": "",
        }])
        lookup_df.to_csv(lookup_path, index=False)

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "output.csv"), \
             patch("pipeline.unified_holdings.ENTITY_LOOKUP_FILE",
                    lookup_path):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

        # No match -> empty string, not NaN
        assert (result["entity_id"] == "").all()

    def test_column_order_preserved(self, tmp_path):
        """Entity enrichment should not change column order."""
        bdc_df = self._make_bdc_df()
        nport_df = self._make_nport_df()

        lookup_path = tmp_path / "entity_lookup.csv"
        pd.DataFrame([{
            "entity_id": "ENT-00000001",
            "canonical_name": "Acme Corporation",
            "normalized_name": "acme corp",
            "issuer_name_variant": "Acme Corp",
            "source": "bdc",
            "occurrence_count": 10,
            "cluster_method": "exact",
            "cusip": "",
            "lei": "",
        }]).to_csv(lookup_path, index=False)

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "output.csv"), \
             patch("pipeline.unified_holdings.ENTITY_LOOKUP_FILE",
                    lookup_path):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

        assert list(result.columns) == UNIFIED_COLUMNS


# ---------------------------------------------------------------------------
# Industry enrichment in build_unified_holdings
# ---------------------------------------------------------------------------

class TestIndustryEnrichment:
    """Tests for extracted_industry population via identifier_extraction_lookup join."""

    def _make_bdc_df(self):
        return pd.DataFrame([{
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Acme Corp | Technology | First Lien Term Loan",
            "fair_value": 1000000.0, "cost": 990000.0,
            "principal_amount": 1000000.0, "interest_rate": 8.5,
            "basis_spread": 3.5, "reference_rate_type": "SOFR",
            "maturity_date": "2028-01-15", "pct_of_net_assets": 0.05,
            "pik_rate": None, "shares_held": None,
            "unrealized_gain_loss": 10000.0, "dimensions_raw": "x=y",
            "investment_type": "", "industry": "", "affiliation": "",
            "period": "2023-03-31",
        }])

    def _make_nport_df(self):
        return pd.DataFrame(columns=[
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit", "other_unit_desc", "exchange_rate",
            "other_asset", "other_issuer", "sub_type", "derivative_cat",
            "is_default", "other_identifier", "currency_code",
        ])

    def test_industry_populated_when_lookup_exists(self, tmp_path):
        """When identifier_extraction_lookup.csv exists, extracted_industry is filled."""
        bdc_df = self._make_bdc_df()
        nport_df = self._make_nport_df()

        lookup_path = tmp_path / "identifier_extraction_lookup.csv"
        pd.DataFrame([{
            "bdc_investment_identifier": "Acme Corp | Technology | First Lien Term Loan",
            "extracted_company": "Acme Corp",
            "extracted_industry": "Technology",
            "extracted_maturity_date": "",
        }]).to_csv(lookup_path, index=False)

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "output.csv"), \
             patch("pipeline.unified_holdings.ENTITY_LOOKUP_FILE",
                    tmp_path / "nonexistent.csv"), \
             patch("pipeline.unified_holdings.IDENTIFIER_EXTRACTION_LOOKUP_FILE",
                    lookup_path):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

        acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert acme["extracted_industry"] == "Technology"

    def test_industry_empty_when_no_lookup(self, tmp_path):
        """When no lookup file exists, extracted_industry stays empty."""
        bdc_df = self._make_bdc_df()
        nport_df = self._make_nport_df()

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "output.csv"), \
             patch("pipeline.unified_holdings.ENTITY_LOOKUP_FILE",
                    tmp_path / "nonexistent.csv"), \
             patch("pipeline.unified_holdings.IDENTIFIER_EXTRACTION_LOOKUP_FILE",
                    tmp_path / "nonexistent_lookup.csv"):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

        assert (result["extracted_industry"] == "").all()

    def test_nport_rows_not_affected(self, tmp_path):
        """N-PORT rows should not get industry from BDC lookup."""
        bdc_df = self._make_bdc_df()
        nport_df = pd.DataFrame([{
            "accession_number": "0002-45", "holding_id": "H001",
            "issuer_name": "Some Borrower", "issuer_lei": "",
            "issuer_title": "Term Loan", "issuer_cusip": "",
            "currency_value": 1000000, "percentage": 0.01,
            "asset_cat": "LON", "issuer_type": "CORP",
            "investment_country": "US", "is_restricted_security": "N",
            "fair_value_level": 3, "maturity_date": "",
            "coupon_type": "", "annualized_rate": 5.0,
            "identifier_isin": "", "identifier_ticker": "",
            "payoff_profile": "Long", "cik": "456",
            "registrant_name": "Test Fund", "filing_date": "2023-07-15",
            "report_date": "2023-06-30", "series_name": "S1",
            "series_id": "S001", "quarter": "2023q2",
            "balance": 1000000, "unit": "PA",
        }])

        lookup_path = tmp_path / "identifier_extraction_lookup.csv"
        pd.DataFrame([{
            "bdc_investment_identifier": "Acme Corp | Technology | First Lien Term Loan",
            "extracted_company": "Acme Corp",
            "extracted_industry": "Technology",
            "extracted_maturity_date": "",
        }]).to_csv(lookup_path, index=False)

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "output.csv"), \
             patch("pipeline.unified_holdings.ENTITY_LOOKUP_FILE",
                    tmp_path / "nonexistent.csv"), \
             patch("pipeline.unified_holdings.IDENTIFIER_EXTRACTION_LOOKUP_FILE",
                    lookup_path):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

        nport_rows = result[result["source"] == "nport"]
        assert (nport_rows["extracted_industry"] == "").all()


# ---------------------------------------------------------------------------
# New N-PORT unified columns
# ---------------------------------------------------------------------------

class TestNewNportUnifiedColumns:
    """Tests for nport_is_default, nport_are_interest_payments_in_arrears, etc."""

    def _make_nport_df(self, rows):
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_new_columns_present(self):
        """New nport_* columns should appear in unified output."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "issuer_name": "Test Co", "currency_value": 1000000,
            "is_default": "N", "currency_code": "USD",
            "liquidity_classification": "Moderately Liquid",
            "are_any_interest_payment": "Y",
            "is_any_portion_interest_paid": "N",
        }])
        result = _prepare_nport(df)
        assert "nport_is_default" in result.columns
        assert "nport_are_interest_payments_in_arrears" in result.columns
        assert "nport_is_paid_in_kind" in result.columns
        assert "nport_currency_code" in result.columns
        assert "nport_liquidity_classification" in result.columns
        row = result.iloc[0]
        assert row["nport_is_default"] == "N"
        assert row["nport_are_interest_payments_in_arrears"] == "Y"
        assert row["nport_is_paid_in_kind"] == "N"
        assert row["nport_currency_code"] == "USD"
        assert row["nport_liquidity_classification"] == "Moderately Liquid"

    def test_bdc_side_empty(self):
        """BDC rows should have empty nport_* columns."""
        bdc_df = pd.DataFrame([{
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "TestCo | Loan",
            "fair_value": 1000000.0, "cost": 990000.0,
            "principal_amount": 1000000.0, "interest_rate": 8.5,
            "basis_spread": 3.5, "reference_rate_type": "SOFR",
            "maturity_date": "2028-01-15", "pct_of_net_assets": 0.05,
            "pik_rate": None, "shares_held": None,
            "unrealized_gain_loss": 10000.0, "dimensions_raw": "x=y",
            "investment_type": "", "industry": "", "affiliation": "",
            "period": "2023-03-31",
        }])
        from pipeline.unified_holdings import _prepare_bdc
        result = _prepare_bdc(bdc_df)
        assert result.iloc[0]["nport_is_default"] == ""
        assert result.iloc[0]["nport_currency_code"] == ""
        assert result.iloc[0]["nport_liquidity_classification"] == ""

    def test_missing_columns_handled(self):
        """When nport_df lacks new columns, they default to empty."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "issuer_name": "Test Co", "currency_value": 1000000,
        }])
        # No is_default, currency_code, etc. -- column guard should add them
        result = _prepare_nport(df)
        assert result.iloc[0]["nport_is_default"] == ""
        assert result.iloc[0]["nport_currency_code"] == ""


# ---------------------------------------------------------------------------
# Part 1: Bare leaked header filtering (new aggregate patterns)
# ---------------------------------------------------------------------------

class TestBareLeakedHeaders:
    """Tests for new _BDC_AGGREGATE_EXACT entries and GICS labels."""

    def test_senior_secured_loans_filtered(self):
        assert _is_bdc_aggregate_row("Senior Secured Loans")

    def test_senior_secured_notes_filtered(self):
        assert _is_bdc_aggregate_row("Senior Secured Notes")

    def test_first_lien_filtered(self):
        assert _is_bdc_aggregate_row("First Lien")

    def test_second_lien_filtered(self):
        assert _is_bdc_aggregate_row("Second Lien")

    def test_equity_other_filtered(self):
        assert _is_bdc_aggregate_row("Equity/Other")

    def test_clo_filtered(self):
        assert _is_bdc_aggregate_row("Collateralized Loan Obligation")

    def test_clo_subordinated_notes_filtered(self):
        assert _is_bdc_aggregate_row("CLO Subordinated Notes")

    def test_largest_portfolio_company_investment_filtered(self):
        assert _is_bdc_aggregate_row("Largest Portfolio Company Investment")

    def test_largest_portfolio_company_pattern(self):
        """Substring pattern catches variations."""
        assert _is_bdc_aggregate_row("Largest Portfolio Company by Fair Value")

    # Multi-word GICS labels as bare identifiers
    def test_gics_aerospace_defense_filtered(self):
        assert _is_bdc_aggregate_row("Aerospace & Defense")

    def test_gics_hotels_restaurants_leisure_filtered(self):
        assert _is_bdc_aggregate_row("Hotels, Restaurants & Leisure")

    def test_gics_oil_gas_consumable_fuels_filtered(self):
        assert _is_bdc_aggregate_row("Oil, Gas & Consumable Fuels")

    def test_gics_capital_markets_filtered(self):
        assert _is_bdc_aggregate_row("Capital Markets")

    def test_gics_it_services_filtered(self):
        assert _is_bdc_aggregate_row("IT Services")

    def test_bdc_specific_high_tech_industries_filtered(self):
        assert _is_bdc_aggregate_row("High Tech Industries")

    def test_bdc_specific_business_services_filtered(self):
        assert _is_bdc_aggregate_row("Business Services")

    def test_bdc_specific_hotel_gaming_leisure_filtered(self):
        assert _is_bdc_aggregate_row("Hotel, Gaming & Leisure")

    def test_bdc_specific_food_beverage_filtered(self):
        assert _is_bdc_aggregate_row("Food & Beverage")

    # False-positive guards: company names containing industry words
    def test_company_aerospace_defense_inc_not_filtered(self):
        """Real company with industry words in name should NOT be filtered."""
        assert not _is_bdc_aggregate_row(
            "Aerospace & Defense Holdings, Inc. - First Lien Term Loan"
        )

    def test_company_software_corp_not_filtered(self):
        """'Software Corp - Term Loan' is a real holding, not a label."""
        assert not _is_bdc_aggregate_row("Software Corp - Term Loan")

    def test_company_capital_markets_llc_not_filtered(self):
        assert not _is_bdc_aggregate_row("Capital Markets Solutions LLC - Senior Note")

    def test_first_lien_in_full_identifier_not_filtered(self):
        """'First Lien' alone is filtered, but embedded in an identifier is not."""
        assert not _is_bdc_aggregate_row("Acme Corp - First Lien Term Loan")

    def test_debt_equity_securities_pattern(self):
        assert _is_bdc_aggregate_row("Debt & Equity Securities at Fair Value")


class TestBareLeakedHeadersSqlPath:
    """Verify new aggregate entries work through _prepare_bdc SQL pipeline."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_gics_label_filtered_via_sql(self):
        """GICS industry label as bare identifier is filtered in SQL path."""
        df = self._make_bdc_df([
            {"investment_identifier": "Aerospace & Defense",
             "cik": "123", "fair_value": 5000000},
            {"investment_identifier": "Acme Corp - First Lien Term Loan",
             "cik": "123", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_senior_secured_loans_filtered_via_sql(self):
        df = self._make_bdc_df([
            {"investment_identifier": "Senior Secured Loans",
             "cik": "123", "fair_value": 10000000},
            {"investment_identifier": "Acme Corp - Senior Secured Loan",
             "cik": "123", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"


# ---------------------------------------------------------------------------
# Part 2: Industry-prefix re-split (Python parser)
# ---------------------------------------------------------------------------

class TestParseBdcIdentifierIndustryPrefix:
    """Tests for industry-prefix detection in _parse_bdc_identifier."""

    def test_single_word_industry_3_segments(self):
        """Software - Acme Corp - First Lien -> issuer=Acme Corp."""
        issuer, instr = _parse_bdc_identifier(
            "Software - Acme Corp - First Lien Term Loan"
        )
        assert issuer == "Acme Corp"
        assert instr == "First Lien Term Loan"

    def test_multiword_gics_3_segments(self):
        """Aerospace & Defense - Boeing Corp - Senior Note."""
        issuer, instr = _parse_bdc_identifier(
            "Aerospace & Defense - Boeing Corp - Senior Note"
        )
        assert issuer == "Boeing Corp"
        assert instr == "Senior Note"

    def test_4_segments_with_industry_prefix(self):
        """Healthcare - MedCo Inc - First Lien - Term Loan."""
        issuer, instr = _parse_bdc_identifier(
            "Healthcare - MedCo Inc - First Lien - Term Loan"
        )
        assert issuer == "MedCo Inc"
        assert instr == "First Lien - Term Loan"

    def test_industry_prefix_only_2_segments(self):
        """Software - Acme Corp (only 2 segments) -> should NOT re-split."""
        issuer, instr = _parse_bdc_identifier("Software - Acme Corp")
        # With only 2 segments, first seg is treated as issuer (default behavior)
        assert issuer == "Software"
        assert instr == "Acme Corp"

    def test_non_industry_first_segment_unchanged(self):
        """Acme Corp (not an industry) - Term Loan -> unchanged."""
        issuer, instr = _parse_bdc_identifier("Acme Corp - Term Loan")
        assert issuer == "Acme Corp"
        assert instr == "Term Loan"

    def test_bdc_specific_label(self):
        """High Tech Industries - DataCo LLC - Revolver."""
        issuer, instr = _parse_bdc_identifier(
            "High Tech Industries - DataCo LLC - Revolver"
        )
        assert issuer == "DataCo LLC"
        assert instr == "Revolver"

    def test_case_insensitive_industry_match(self):
        """INSURANCE - Acme Corp - Term Loan (uppercase)."""
        issuer, instr = _parse_bdc_identifier(
            "INSURANCE - Acme Corp - Term Loan"
        )
        # _INDUSTRY_LABELS stores lowercase; .lower() comparison
        assert issuer == "Acme Corp"
        assert instr == "Term Loan"

    def test_energy_prefix(self):
        """Energy - OilCo LLC - Senior Secured Note."""
        issuer, instr = _parse_bdc_identifier(
            "Energy - OilCo LLC - Senior Secured Note"
        )
        assert issuer == "OilCo LLC"
        assert instr == "Senior Secured Note"

    def test_quantity_stripped_after_industry_split(self):
        """Insurance - WidgetCo - $1,000,000 First Lien Term Loan."""
        issuer, instr = _parse_bdc_identifier(
            "Insurance - WidgetCo - $1,000,000 First Lien Term Loan"
        )
        assert issuer == "WidgetCo"
        assert instr == "First Lien Term Loan"

    # Goldman Sachs hierarchical format (multiple segment counts)
    def test_gs_4segment_regular_dash(self):
        """Goldman Sachs 4-segment format with regular dashes."""
        raw = (
            "Investment Debt Investments - 116.03% United States"
            " - 105.72% 1st Lien/Senior Secured Debt"
            " - 95.93% Physician Partners LLC Industry Software"
            " Interest Rate 9.46%"
        )
        issuer, instr = _parse_bdc_identifier(raw)
        assert issuer == "Physician Partners LLC"
        assert "Debt Investments" in instr

    def test_gs_4segment_en_dash(self):
        """Goldman Sachs 4-segment format with en-dash delimiters."""
        raw = (
            "Investment Debt Investments \u2013 116.03% United States"
            " \u2013 105.72% 1st Lien/Senior Secured Debt"
            " \u2013 95.93% Physician Partners LLC Industry Software"
            " Interest Rate 9.46%"
        )
        issuer, instr = _parse_bdc_identifier(raw)
        assert issuer == "Physician Partners LLC"
        assert "Debt Investments" in instr

    def test_gs_4segment_equity(self):
        """Goldman Sachs equity format."""
        raw = (
            "Investment Equity Securities - 10.31% United States"
            " - 10.31% Common Stock"
            " - 3.78% Acme Holdings Inc Interest Rate 0.00%"
        )
        issuer, instr = _parse_bdc_identifier(raw)
        assert issuer == "Acme Holdings Inc"
        assert "Equity Securities" in instr

    def test_gs_4segment_no_keyword_fallback(self):
        """Company name with no financial-term keyword -> take full text."""
        raw = (
            "Investment Debt Investments - 50.00% United States"
            " - 40.00% 2nd Lien/Senior Secured Debt"
            " - 5.00% Beta Corp LLC"
        )
        issuer, instr = _parse_bdc_identifier(raw)
        assert issuer == "Beta Corp LLC"

    def test_gs_2segment(self):
        """Goldman Sachs 2-segment format."""
        raw = (
            "Investment 1st Lien/Senior Secured Debt"
            " - 103.88% Ankura Consulting Group, LLC"
            " Industry Commercial Services Interest Rate 9.93%"
        )
        issuer, instr = _parse_bdc_identifier(raw)
        assert issuer == "Ankura Consulting Group, LLC"
        assert "1st Lien/Senior Secured Debt" in instr

    def test_gs_2segment_unitranche(self):
        """Goldman Sachs 2-segment unitranche format."""
        raw = (
            "Investment 1st Lien/Last-Out Unitranche (11)"
            " - 6.64% Doxim, Inc. Industry Financial Services"
            " Interest Rate 11.86%"
        )
        issuer, instr = _parse_bdc_identifier(raw)
        assert issuer == "Doxim, Inc."
        assert "1st Lien/Last-Out Unitranche (11)" in instr

    def test_gs_3segment(self):
        """Goldman Sachs 3-segment format."""
        raw = (
            "Investment Debt Investments"
            " - 194.03% United Kingdom -2.36% 1st Lien/Senior Secured Debt"
            " - 2.36% Bigchange Group Limited Industry Software"
            " Interest Rate 11.20%"
        )
        issuer, instr = _parse_bdc_identifier(raw)
        assert issuer == "Bigchange Group Limited"

    def test_gs_1segment_no_dash(self):
        """Goldman Sachs 1-segment (no dash separator)."""
        raw = (
            "Investment Unsecured Debt 0.52% CivicPlus LLC"
            " Industry Software Interest Rate 17.09%"
        )
        issuer, instr = _parse_bdc_identifier(raw)
        assert issuer == "CivicPlus LLC"
        assert "Unsecured Debt" in instr

    def test_existing_3segment_industry_unaffected(self):
        """Existing 3-segment industry-prefix format is unchanged by GS logic."""
        issuer, instr = _parse_bdc_identifier(
            "Healthcare - MedCo Inc - First Lien - Term Loan"
        )
        assert issuer == "MedCo Inc"
        assert "First Lien" in instr

    def test_existing_2segment_unaffected(self):
        """Existing 2-segment format is unchanged by GS logic."""
        issuer, instr = _parse_bdc_identifier("Acme Corp - Term Loan")
        assert issuer == "Acme Corp"
        assert instr == "Term Loan"


# ---------------------------------------------------------------------------
# Part 2: Pipe-format parsing (Python parser)
# ---------------------------------------------------------------------------

class TestParseBdcIdentifierPipeFormat:
    """Tests for pipe-separator format in _parse_bdc_identifier."""

    def test_3_pipe_segments(self):
        """Type | Industry | Company -> issuer=Company."""
        issuer, instr = _parse_bdc_identifier(
            "Senior Secured Loans | Technology | Acme Corp"
        )
        assert issuer == "Acme Corp"
        assert "Senior Secured Loans" in instr
        assert "Technology" in instr

    def test_4_pipe_segments(self):
        """Type | Industry | Company | Instrument."""
        issuer, instr = _parse_bdc_identifier(
            "Senior Secured Loans | Technology | Acme Corp | First Lien"
        )
        assert issuer == "Acme Corp"
        assert "Senior Secured Loans" in instr
        assert "Technology" in instr
        assert "First Lien" in instr

    def test_pipe_with_2_segments(self):
        """2 pipe segments -> issuer = segment 1, instrument = segment 2."""
        issuer, instr = _parse_bdc_identifier("Type | Value")
        assert issuer == "Type"
        assert instr == "Value"

    def test_pipe_2_segments_affiliation(self):
        """2 pipe segments with affiliation tag."""
        issuer, instr = _parse_bdc_identifier(
            "Guidehouse, Inc. | Non-Affiliated Issuer"
        )
        assert issuer == "Guidehouse, Inc."
        assert instr == "Non-Affiliated Issuer"

    def test_pipe_2_segments_instrument(self):
        """2 pipe segments with instrument description."""
        issuer, instr = _parse_bdc_identifier(
            "CRCI Longhorn Holdings, Inc. | First lien"
        )
        assert issuer == "CRCI Longhorn Holdings, Inc."
        assert instr == "First lien"

    def test_pipe_format_preserves_company_name(self):
        """SLR-style: loan type | industry | company name with comma."""
        issuer, instr = _parse_bdc_identifier(
            "Second Lien | Healthcare | MedCo, Inc. | Term Loan B"
        )
        assert issuer == "MedCo, Inc."
        assert "Healthcare" in instr


# ---------------------------------------------------------------------------
# Part 2: Industry-prefix re-split (SQL path via _prepare_bdc)
# ---------------------------------------------------------------------------

class TestIndustryPrefixSqlPath:
    """Verify industry-prefix and pipe-format parsing through full SQL pipeline."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_kayne_format_3_segments(self):
        """Kayne Anderson: 'Software - Acme Corp - First Lien' -> issuer=Acme Corp."""
        df = self._make_bdc_df([{
            "investment_identifier": "Software - Acme Corp - First Lien Term Loan",
            "cik": "1747172", "fair_value": 1000000, "interest_rate": 8.5,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Acme Corp"
        assert "First Lien Term Loan" in result.iloc[0]["instrument_description"]
        assert result.iloc[0]["asset_category"] == "LOAN"

    def test_kayne_format_4_segments(self):
        """Healthcare - MedCo Inc - First Lien - Term Loan."""
        df = self._make_bdc_df([{
            "investment_identifier": "Healthcare - MedCo Inc - First Lien - Term Loan",
            "cik": "1747172", "fair_value": 2000000, "interest_rate": 9.0,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "MedCo Inc"
        assert "First Lien" in result.iloc[0]["instrument_description"]

    def test_oxford_square_format(self):
        """Oxford Square: 'Media - RadioCo LLC - Senior Secured Note - First Lien'."""
        df = self._make_bdc_df([{
            "investment_identifier": "Media - RadioCo LLC - Senior Secured Note - First Lien",
            "cik": "1379785", "fair_value": 500000, "interest_rate": 7.5,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "RadioCo LLC"
        assert "Senior Secured Note" in result.iloc[0]["instrument_description"]

    def test_slr_pipe_format(self):
        """SLR Investment: pipe-separated identifiers."""
        df = self._make_bdc_df([{
            "investment_identifier": "Senior Secured Loans | Technology | Acme Corp | First Lien",
            "cik": "1418076", "fair_value": 1000000, "interest_rate": 10.0,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Acme Corp"
        assert result.iloc[0]["asset_category"] == "LOAN"

    def test_non_industry_prefix_unchanged(self):
        """Normal identifier with no industry prefix stays unchanged."""
        df = self._make_bdc_df([{
            "investment_identifier": "Widget Corp - First Lien Term Loan",
            "cik": "999", "fair_value": 1000000, "interest_rate": 8.0,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Widget Corp"
        assert "First Lien Term Loan" in result.iloc[0]["instrument_description"]

    def test_2_segment_industry_not_resplit(self):
        """'Software - Acme Corp' (only 2 segments) -> default behavior."""
        df = self._make_bdc_df([{
            "investment_identifier": "Software - Acme Corp",
            "cik": "999", "fair_value": 500000, "shares_held": 1000,
        }])
        result = _prepare_bdc(df)
        # With only 2 segments and first=industry, default keeps first as issuer
        assert result.iloc[0]["issuer_name"] == "Software"

    def test_multiword_gics_industry_prefix(self):
        """'Aerospace & Defense - BombCo Inc - Senior Note'."""
        df = self._make_bdc_df([{
            "investment_identifier": "Aerospace & Defense - BombCo Inc - Senior Note",
            "cik": "1747172", "fair_value": 3000000, "interest_rate": 6.5,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "BombCo Inc"
        assert "Senior Note" in result.iloc[0]["instrument_description"]

    def test_classification_correct_after_resplit(self):
        """After industry-prefix re-split, asset classification still works."""
        df = self._make_bdc_df([
            {"investment_identifier": "Technology - TechCo LLC - Common Stock",
             "cik": "1747172", "fair_value": 100000, "shares_held": 5000},
            {"investment_identifier": "Insurance - InsureCo - LP Interest in Growth Fund",
             "cik": "1747172", "fair_value": 200000},
        ])
        result = _prepare_bdc(df)
        tech_row = result[result["issuer_name"] == "TechCo LLC"].iloc[0]
        assert tech_row["asset_category"] == "EQUITY_COMMON"

        insure_row = result[result["issuer_name"] == "InsureCo"].iloc[0]
        assert insure_row["asset_category"] == "FUND"

    def test_mixed_formats_in_same_filing(self):
        """Mix of normal and industry-prefix identifiers in the same CIK."""
        df = self._make_bdc_df([
            {"investment_identifier": "Software - WidgetCo - Term Loan",
             "cik": "100", "accession_number": "001",
             "fair_value": 1000000, "interest_rate": 8.0},
            {"investment_identifier": "Acme Corp - First Lien Term Loan",
             "cik": "100", "accession_number": "001",
             "fair_value": 2000000, "interest_rate": 9.0},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        issuers = set(result["issuer_name"].tolist())
        assert "WidgetCo" in issuers
        assert "Acme Corp" in issuers

    def test_gs_4segment_format_sql(self):
        """Goldman Sachs 4-segment format parsed correctly via SQL."""
        raw = (
            "Investment Debt Investments - 116.03% United States"
            " - 105.72% 1st Lien/Senior Secured Debt"
            " - 95.93% Physician Partners LLC Industry Software"
            " Interest Rate 9.46%"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "1920145", "fair_value": 5000000, "interest_rate": 9.46,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Physician Partners LLC"
        assert "Debt Investments" in result.iloc[0]["instrument_description"]

    def test_gs_4segment_en_dash_sql(self):
        """Goldman Sachs en-dash delimiters normalised and parsed."""
        raw = (
            "Investment Debt Investments \u2013 116.03% United States"
            " \u2013 105.72% 1st Lien/Senior Secured Debt"
            " \u2013 95.93% Physician Partners LLC Industry Software"
            " Interest Rate 9.46%"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "1920145", "fair_value": 5000000, "interest_rate": 9.46,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Physician Partners LLC"

    def test_gs_4segment_equity_sql(self):
        """Goldman Sachs equity identifier."""
        raw = (
            "Investment Equity Securities - 10.31% United States"
            " - 10.31% Common Stock"
            " - 3.78% Acme Holdings Inc Interest Rate 0.00%"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "1920145", "fair_value": 2000000, "shares_held": 10000,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Holdings Inc"
        assert "Equity Securities" in result.iloc[0]["instrument_description"]

    def test_gs_2segment_format_sql(self):
        """Goldman Sachs 2-segment format via SQL."""
        raw = (
            "Investment 1st Lien/Senior Secured Debt"
            " - 103.88% Ankura Consulting Group, LLC"
            " Industry Commercial Services Interest Rate 9.93%"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "1920145", "fair_value": 3000000, "interest_rate": 9.93,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Ankura Consulting Group, LLC"
        assert "1st Lien/Senior Secured Debt" in result.iloc[0]["instrument_description"]

    def test_gs_1segment_format_sql(self):
        """Goldman Sachs 1-segment (no dash) via SQL."""
        raw = (
            "Investment Unsecured Debt 0.52% CivicPlus LLC"
            " Industry Software Interest Rate 17.09%"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "1920145", "fair_value": 1000000, "interest_rate": 17.09,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "CivicPlus LLC"

    def test_existing_formats_unaffected_by_gs_logic(self):
        """Normal 2-segment and 3-segment identifiers unchanged."""
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp - First Lien Term Loan",
             "cik": "999", "fair_value": 1000000, "interest_rate": 8.0},
            {"investment_identifier": "Technology - DataCo LLC - Revolver",
             "cik": "999", "fair_value": 500000, "interest_rate": 7.0},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        issuers = set(result["issuer_name"].tolist())
        assert "Acme Corp" in issuers
        assert "DataCo LLC" in issuers


# ---------------------------------------------------------------------------
# Industry labels coverage
# ---------------------------------------------------------------------------

class TestIndustryLabelsCompleteness:
    """Verify _INDUSTRY_LABELS contains expected entries."""

    def test_single_word_labels_present(self):
        for label in ["software", "healthcare", "insurance", "energy",
                       "technology", "media", "retail"]:
            assert label in _INDUSTRY_LABELS, f"Missing: {label}"

    def test_multiword_gics_labels_present(self):
        for label in ["aerospace & defense", "capital markets",
                       "hotels, restaurants & leisure", "it services",
                       "oil, gas & consumable fuels"]:
            assert label in _INDUSTRY_LABELS, f"Missing: {label}"

    def test_bdc_specific_labels_present(self):
        for label in ["high tech industries", "business services",
                       "hotel, gaming & leisure", "food & beverage",
                       "banking, finance, insurance & real estate"]:
            assert label in _INDUSTRY_LABELS, f"Missing: {label}"

    def test_geography_labels_present(self):
        for label in ["canada", "europe", "united states", "united kingdom"]:
            assert label in _INDUSTRY_LABELS, f"Missing: {label}"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCli:
    def test_unified_flag_parsing(self):
        """Verify --unified is parsed correctly."""
        from pipeline.main import _parse_args
        import sys

        with patch.object(sys, "argv", ["main", "--unified"]):
            args = _parse_args()
        assert args.unified is True

    def test_no_unified_flag(self):
        from pipeline.main import _parse_args
        import sys

        with patch.object(sys, "argv", ["main"]):
            args = _parse_args()
        assert args.unified is False


# ---------------------------------------------------------------------------
# Change A: Smart Rate Normalization
# ---------------------------------------------------------------------------

class TestNormalizeRate:
    """Unit tests for _normalize_rate()."""

    def test_decimal_to_percentage(self):
        assert _normalize_rate(0.10) == pytest.approx(10.0)

    def test_decimal_small(self):
        assert _normalize_rate(0.085) == pytest.approx(8.5)

    def test_already_percentage(self):
        assert _normalize_rate(10.5) == pytest.approx(10.5)

    def test_already_percentage_high(self):
        """25% CLO subordinated note rate stays as-is."""
        assert _normalize_rate(25.0) == pytest.approx(25.0)

    def test_basis_points_to_percentage(self):
        assert _normalize_rate(575.0) == pytest.approx(5.75)

    def test_basis_points_large(self):
        assert _normalize_rate(1050.0) == pytest.approx(10.50)

    def test_none_returns_none(self):
        assert _normalize_rate(None) is None

    def test_zero_returns_zero(self):
        assert _normalize_rate(0.0) == pytest.approx(0.0)

    def test_boundary_half(self):
        """0.50 is in the decimal band (<=0.50), so *100 = 50.0."""
        assert _normalize_rate(0.50) == pytest.approx(50.0)

    def test_boundary_just_above_50(self):
        """50.01 is in the bps band (>50), so /100 = 0.5001."""
        assert _normalize_rate(50.01) == pytest.approx(0.5001)

    def test_negative_decimal(self):
        """Negative rate (rare but possible) in decimal -> *100."""
        assert _normalize_rate(-0.02) == pytest.approx(-2.0)


class TestRateNormalizationSqlPath:
    """Verify rate normalization through _prepare_bdc SQL pipeline."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_decimal_rate_converted(self):
        """BDC row with decimal interest_rate (0.085) -> 8.5%."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "cik": "123", "fair_value": 1000000, "interest_rate": 0.085,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["interest_rate"] == pytest.approx(8.5)

    def test_percentage_rate_not_doubled(self):
        """BDC row with percentage-scale rate (8.5) is NOT double-converted."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "cik": "123", "fair_value": 1000000, "interest_rate": 8.5,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["interest_rate"] == pytest.approx(8.5)

    def test_bps_basis_spread_divided(self):
        """BDC row with bps-scale basis_spread (575) -> 5.75%."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "cik": "123", "fair_value": 1000000,
            "interest_rate": 0.10, "basis_spread": 575.0,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["basis_spread"] == pytest.approx(5.75)

    def test_pct_of_net_assets_normalized(self):
        """pct_of_net_assets 0.05 -> 5.0%."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "cik": "123", "fair_value": 1000000, "pct_of_net_assets": 0.05,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["pct_of_net_assets"] == pytest.approx(5.0)

    def test_pik_rate_decimal_converted(self):
        """PIK rate 0.02 -> 2.0%."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "cik": "123", "fair_value": 1000000,
            "interest_rate": 0.10, "pik_rate": 0.02,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["pik_rate"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Change B: Pipe-Format Direction (affiliation detection)
# ---------------------------------------------------------------------------

class TestParseBdcIdentifierAffiliationPipe:
    """Tests for affiliation-format pipe detection in _parse_bdc_identifier."""

    def test_affiliation_format_non_affiliated(self):
        """'Company | Instrument | Non-Affiliated Issuer' -> issuer = Company."""
        issuer, instr = _parse_bdc_identifier(
            "Blue Owl Corp | Senior Secured Term Loan | Non-Affiliated Issuer"
        )
        assert issuer == "Blue Owl Corp"
        assert instr == "Senior Secured Term Loan"

    def test_affiliation_format_affiliated(self):
        """'Company | Instrument | Affiliated' -> issuer = Company."""
        issuer, instr = _parse_bdc_identifier(
            "Widget Holdings LLC | First Lien | Affiliated"
        )
        assert issuer == "Widget Holdings LLC"
        assert instr == "First Lien"

    def test_affiliation_format_controlled(self):
        """'Company | Instrument | Controlled' -> issuer = Company."""
        issuer, instr = _parse_bdc_identifier(
            "Portfolio Co Inc | Equity Interest | Controlled"
        )
        assert issuer == "Portfolio Co Inc"
        assert instr == "Equity Interest"

    def test_affiliation_format_non_control_affiliate(self):
        """'Company | Instrument | Non-Control/Non-Affiliate'."""
        issuer, instr = _parse_bdc_identifier(
            "Acme Corp | Revolver | Non-Control/Non-Affiliate"
        )
        assert issuer == "Acme Corp"
        assert instr == "Revolver"

    def test_slr_format_unchanged(self):
        """SLR format still works: 'Type | Industry | Company | ...'."""
        issuer, instr = _parse_bdc_identifier(
            "Senior Secured Loans | Technology | Acme Corp | First Lien"
        )
        assert issuer == "Acme Corp"
        assert "Senior Secured Loans" in instr

    def test_2_segment_pipe_splits(self):
        """2 pipe segments -> issuer = segment 1, instrument = segment 2."""
        issuer, instr = _parse_bdc_identifier("Type | Value")
        assert issuer == "Type"
        assert instr == "Value"

    def test_affiliation_tags_constant_completeness(self):
        """Verify key affiliation tags are present."""
        for tag in ["non-affiliated issuer", "affiliated issuer",
                     "non-affiliated", "affiliated", "controlled"]:
            assert tag in _AFFILIATION_TAGS


class TestPipeFormatSqlPath:
    """Verify pipe-format direction fix through _prepare_bdc SQL pipeline."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_affiliation_pipe_issuer_via_sql(self):
        """Affiliation-format pipe gets correct issuer_name in SQL path."""
        df = self._make_bdc_df([{
            "investment_identifier": "Blue Owl Capital | Senior Secured Loan | Non-Affiliated Issuer",
            "cik": "123", "fair_value": 5000000, "interest_rate": 0.10,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Blue Owl Capital"
        assert result.iloc[0]["instrument_description"] == "Senior Secured Loan"

    def test_affiliation_pipe_not_issuer_name_is_affiliation(self):
        """Affiliation tag should NOT become the issuer_name."""
        df = self._make_bdc_df([{
            "investment_identifier": "Golub Capital Inc | Term Loan B | Affiliated Issuer",
            "cik": "456", "fair_value": 3000000, "interest_rate": 0.09,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] != "Affiliated Issuer"
        assert result.iloc[0]["issuer_name"] == "Golub Capital Inc"

    def test_mixed_pipe_formats_same_filing(self):
        """Both SLR and affiliation pipe formats in the same filing."""
        df = self._make_bdc_df([
            {"investment_identifier": "Senior Secured | Tech | DataCo | First Lien",
             "cik": "100", "accession_number": "001",
             "fair_value": 1000000, "interest_rate": 0.08},
            {"investment_identifier": "WidgetCo LLC | Revolver | Non-Affiliated",
             "cik": "100", "accession_number": "001",
             "fair_value": 2000000, "interest_rate": 0.07},
        ])
        result = _prepare_bdc(df)
        issuers = set(result["issuer_name"].tolist())
        assert "DataCo" in issuers
        assert "WidgetCo LLC" in issuers


# ---------------------------------------------------------------------------
# Change C: Expanded Subtotal Filtering
# ---------------------------------------------------------------------------

class TestExpandedSubtotalFiltering:
    """Tests for new 'total X' subtotal patterns."""

    def test_total_affiliates_caught(self):
        assert _is_bdc_aggregate_row("Total Affiliates")

    def test_total_senior_secured_loan_caught(self):
        assert _is_bdc_aggregate_row("Total Senior Secured Loan")

    def test_total_equity_exact_caught(self):
        """'Total Equity' exact match."""
        assert _is_bdc_aggregate_row("Total Equity")

    def test_total_warrants_exact_caught(self):
        assert _is_bdc_aggregate_row("Total Warrants")

    def test_total_first_lien_caught(self):
        assert _is_bdc_aggregate_row("Total First Lien Debt")

    def test_total_second_lien_caught(self):
        assert _is_bdc_aggregate_row("Total Second Lien Debt")

    def test_total_subordinated_caught(self):
        assert _is_bdc_aggregate_row("Total Subordinated Debt")

    def test_total_portfolio_caught(self):
        assert _is_bdc_aggregate_row("Total Portfolio Investments")

    def test_total_safety_holdings_not_caught(self):
        """'Total Safety Holdings LLC' is a real company, NOT a subtotal."""
        assert not _is_bdc_aggregate_row(
            "Total Safety Holdings LLC - First Lien Term Loan"
        )

    def test_total_access_elevator_not_caught(self):
        """'Total Access Elevator, Inc.' is a real company."""
        assert not _is_bdc_aggregate_row(
            "Total Access Elevator, Inc. - Senior Secured Note"
        )


class TestExpandedSubtotalSqlPath:
    """Verify expanded subtotals are filtered in _prepare_bdc SQL pipeline."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_total_affiliates_filtered_sql(self):
        df = self._make_bdc_df([
            {"investment_identifier": "Total Affiliates",
             "cik": "123", "fair_value": 50000000},
            {"investment_identifier": "Acme Corp - Term Loan",
             "cik": "123", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"


# ---------------------------------------------------------------------------
# Change D: N-PORT Fund-Like Name Detection
# ---------------------------------------------------------------------------

class TestNportNullFvlAndHedgeFund:
    """Tests for NULL fair_value_level inclusion and hedge fund exclusion."""

    def _make_nport_df(self, rows):
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_null_fvl_included(self):
        """Holdings with NULL fair_value_level should now be included."""
        df = self._make_nport_df([
            {"fair_value_level": None, "cik": "100", "asset_cat": "EC",
             "issuer_type": "CORP", "issuer_name": "Some BDC Corp",
             "currency_value": 1000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1

    def test_empty_fvl_included(self):
        """Holdings with empty-string fair_value_level should be included."""
        df = self._make_nport_df([
            {"fair_value_level": "", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "issuer_name": "Private Co",
             "currency_value": 2000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1

    def test_level3_still_included(self):
        """Existing Level 3 holdings still pass through."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "issuer_name": "Borrower A",
             "currency_value": 5000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1

    def test_level1_still_excluded(self):
        """Level 1 holdings should still be excluded."""
        df = self._make_nport_df([
            {"fair_value_level": "1", "cik": "100", "asset_cat": "DBT",
             "issuer_type": "CORP", "issuer_name": "Public Co",
             "currency_value": 3000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 0

    def test_ec_corporate_credit_fund_reclassed(self):
        """EC+CORPORATE BDC-named holdings get issuer_category -> FUND."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "EC",
             "issuer_type": "CORP",
             "issuer_name": "Barings Private Credit Corp.",
             "currency_value": 5000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_ec_corporate_normal_stays_corporate(self):
        """EC+CORPORATE with normal company name stays CORPORATE."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "EC",
             "issuer_type": "CORP", "issuer_name": "Microsoft Corp.",
             "currency_value": 5000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_hedge_fund_flows_through(self):
        """PF+OTHER named holdings with no credit/PE signal now flow through (not excluded)."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "OTHER",
             "issuer_type": "PF",
             "issuer_name": "Millennium International Ltd.",
             "currency_value": 5000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1

    def test_pf_credit_signal_kept(self):
        """PF+OTHER named holdings WITH credit signal are kept."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "OTHER",
             "issuer_type": "PF",
             "issuer_name": "Apollo Senior Credit Fund III",
             "currency_value": 5000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1

    def test_pf_pe_signal_kept(self):
        """PF+OTHER named holdings WITH PE signal are kept."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "OTHER",
             "issuer_type": "PF",
             "issuer_name": "Blackstone Private Equity Partners VIII",
             "currency_value": 5000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1

    def test_pf_other_empty_name_kept(self):
        """PF+OTHER with empty issuer_name should NOT be excluded (only named ones)."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "OTHER",
             "issuer_type": "PF", "issuer_name": "",
             "currency_value": 1000000},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1


class TestNportFundDetection:
    """Tests for N-PORT fund-like issuer name reclassification."""

    def _make_nport_df(self, rows):
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_lp_suffix_reclassified_to_fund(self):
        """OTHER+CORP with 'L.P.' -> FUND."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "OTHER", "issuer_type": "CORP",
            "issuer_name": "Apollo Investment Fund IX, L.P.",
            "currency_value": 5000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_fund_keyword_reclassified(self):
        """OTHER+CORP with 'Fund' in name -> FUND."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "OTHER", "issuer_type": "CORP",
            "issuer_name": "Blackstone Credit Fund II",
            "currency_value": 3000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_capital_partners_reclassified(self):
        """OTHER+CORP with 'Capital Partners' -> FUND."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "OTHER", "issuer_type": "CORP",
            "issuer_name": "Ares Capital Partners IV",
            "currency_value": 2000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_lp_with_inc_stays_corporate(self):
        """OTHER+CORP with 'Inc.' + 'L.P.' -> stays CORPORATE (operating company LP)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "OTHER", "issuer_type": "CORP",
            "issuer_name": "Acme Industries Inc., L.P.",
            "currency_value": 1000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_lon_corp_stays_corporate(self):
        """LON+CORP -> stays CORPORATE (not OTHER asset, rule doesn't apply)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "issuer_name": "Apollo Investment Fund IX, L.P.",
            "currency_value": 5000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_other_fund_issuer_stays_fund(self):
        """OTHER+PF (already fund) stays FUND when it has a credit signal."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "OTHER", "issuer_type": "PF",
            "issuer_name": "Some Private Credit Fund LP",
            "currency_value": 2000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_other_corp_normal_company_stays_corporate(self):
        """OTHER+CORP with normal company name -> stays CORPORATE."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "OTHER", "issuer_type": "CORP",
            "issuer_name": "Acme Corporation",
            "currency_value": 1000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_buyout_keyword_reclassified(self):
        """OTHER+CORP with 'Buyout' -> FUND."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "OTHER", "issuer_type": "CORP",
            "issuer_name": "KKR North America Buyout",
            "currency_value": 8000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_lp_without_fund_signal_stays_corporate(self):
        """OTHER+CORP with 'L.P.' but no fund co-keyword -> stays CORPORATE."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "OTHER", "issuer_type": "CORP",
            "issuer_name": "ALP CFO 2024, L.P.",
            "currency_value": 2000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_nuss_govt_name_becomes_government(self):
        """NUSS with government keyword in name -> GOVERNMENT."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "DBT", "issuer_type": "NUSS",
            "issuer_name": "RUSSIAN GOVT",
            "currency_value": 5000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "GOVERNMENT"

    def test_nuss_corporate_name_stays_corporate(self):
        """NUSS with corporate name -> CORPORATE (via LON/DBT+OTHER -> CORPORATE)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "NUSS",
            "issuer_name": "Waratek Ltd",
            "currency_value": 3000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    # -- P2/P4/P5: EC+CORP LP fund detection --

    def test_ec_corp_lp_with_fund_cokw_reclassed_to_fund(self):
        """EC+CORP with 'L.P.' + fund co-keyword -> FUND (P2/P4/P5 fix)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "EC", "issuer_type": "CORP",
            "issuer_name": "TPG Partners VIII, L.P.",
            "currency_value": 5000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_ec_corp_lp_real_estate_fund_reclassed(self):
        """EC+CORP RE fund LP -> FUND (P2 fix)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "EC", "issuer_type": "CORP",
            "issuer_name": "Brookfield Real Estate Partners IV, L.P.",
            "currency_value": 8000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_ec_corp_debt_fund_keyword_reclassed(self):
        """EC+CORP with 'debt fund' keyword -> FUND (P4 fix)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "EC", "issuer_type": "CORP",
            "issuer_name": "BSP Debt Fund IV",
            "currency_value": 3000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_ec_corp_secondaries_keyword_reclassed(self):
        """EC+CORP with 'secondaries' keyword -> FUND (P5 fix)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "EC", "issuer_type": "CORP",
            "issuer_name": "Coller International Partners Secondaries",
            "currency_value": 4000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "FUND"

    def test_ec_corp_normal_company_stays_corporate(self):
        """EC+CORP with normal company name -> stays CORPORATE (no false positive)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "EC", "issuer_type": "CORP",
            "issuer_name": "Johnson Controls International PLC",
            "currency_value": 2000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "CORPORATE"

    def test_ec_corp_lp_with_llc_stays_corporate(self):
        """EC+CORP with 'L.P.' + 'LLC' -> stays CORPORATE (operating company)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "EC", "issuer_type": "CORP",
            "issuer_name": "AffiniPay Intermediate Holdings LLC, L.P.",
            "currency_value": 1000000,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_category"] == "CORPORATE"


# ---------------------------------------------------------------------------
# Rate cap tests
# ---------------------------------------------------------------------------

class TestRateCap:
    """Tests for N-PORT interest rate cap at 50%."""

    def _make_nport_df(self, rows):
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row["currency_value"] = 1000000
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_nport_rate_above_50_capped_to_null(self):
        """annualized_rate=100 -> interest_rate is NULL."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "annualized_rate": 100.0,
        }])
        result = _prepare_nport(df)
        assert pd.isna(result.iloc[0]["interest_rate"])

    def test_nport_rate_extreme_capped(self):
        """annualized_rate=11212830 -> interest_rate is NULL."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "annualized_rate": 11212830.0,
        }])
        result = _prepare_nport(df)
        assert pd.isna(result.iloc[0]["interest_rate"])

    def test_nport_rate_below_50_preserved(self):
        """annualized_rate=7.5 -> interest_rate=7.5."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "annualized_rate": 7.5,
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["interest_rate"] == 7.5


# ---------------------------------------------------------------------------
# Name normalization tests
# ---------------------------------------------------------------------------

class TestNameNormalization:
    """Tests for issuer name normalization in BDC and N-PORT preparation."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def _make_nport_df(self, rows):
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row["currency_value"] = 1000000
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_bdc_double_period_collapsed(self):
        """'AI Aqua, Inc..' -> 'AI Aqua, Inc.' (double period collapsed to single)."""
        df = self._make_bdc_df([{
            "investment_identifier": "AI Aqua, Inc.. - Term Loan",
            "cik": "123", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "AI Aqua, Inc."

    def test_bdc_trailing_comma_stripped(self):
        """'Acme Corp,' -> 'Acme Corp'."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp, - Term Loan",
            "cik": "123", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_bdc_whitespace_collapsed(self):
        """'Acme  Corp' -> 'Acme Corp'."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme  Corp - Term Loan",
            "cik": "123", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_nport_trailing_period_preserved(self):
        """'Private Co.' -> 'Private Co.' (single period is abbreviation)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "issuer_name": "Private Co.",
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_name"] == "Private Co."

    def test_normal_name_unchanged(self):
        """'Acme Corp' -> 'Acme Corp' (no change)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "issuer_name": "Acme Corp",
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_name"] == "Acme Corp"


# ---------------------------------------------------------------------------
# Cost proxy tests
# ---------------------------------------------------------------------------

class TestCostProxy:
    """Tests for first-observed fair value as N-PORT cost proxy."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def _make_nport_df(self, rows):
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def _empty_bdc_df(self):
        """Return an empty BDC DataFrame with correct schema (all str dtype)."""
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        return pd.DataFrame({c: pd.Series(dtype=str) for c in cols})

    def _empty_nport_df(self):
        """Return an empty N-PORT DataFrame with correct schema (all str dtype)."""
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        return pd.DataFrame({c: pd.Series(dtype=str) for c in cols})

    def test_nport_gets_first_fv_as_cost(self, tmp_path):
        """N-PORT position with 2 periods: cost filled with earliest FV."""
        nport_df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "issuer_name": "Borrower A",
             "currency_value": 100000, "report_date": "2023-03-31",
             "accession_number": "001"},
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "issuer_name": "Borrower A",
             "currency_value": 110000, "report_date": "2023-06-30",
             "accession_number": "002"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=self._empty_bdc_df(), nport_df=nport_df)
        borrower = result[result["issuer_name"] == "Borrower A"]
        # Both rows should have cost = 100000 (first observed FV)
        assert (borrower["cost"] == 100000.0).all()

    def test_bdc_keeps_real_cost(self, tmp_path):
        """BDC position with real cost: cost stays unchanged."""
        bdc_df = self._make_bdc_df([{
            "cik": "123", "investment_identifier": "Acme Corp - Term Loan",
            "fair_value": 60000, "cost": 50000,
            "report_date": "2023-03-31", "accession_number": "001",
        }])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=bdc_df, nport_df=self._empty_nport_df())
        acme = result[result["issuer_name"] == "Acme Corp"]
        assert acme.iloc[0]["cost"] == 50000.0

    def test_nport_zero_fv_skipped(self, tmp_path):
        """First period FV=0, second FV=100000 -> cost=100000."""
        nport_df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "issuer_name": "Borrower B",
             "currency_value": 0, "report_date": "2023-03-31",
             "accession_number": "001"},
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "issuer_name": "Borrower B",
             "currency_value": 100000, "report_date": "2023-06-30",
             "accession_number": "002"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=self._empty_bdc_df(), nport_df=nport_df)
        borrower = result[result["issuer_name"] == "Borrower B"]
        assert (borrower["cost"] == 100000.0).all()

    def test_nport_no_fv_stays_null(self, tmp_path):
        """All FV=0/NULL -> cost stays NULL."""
        nport_df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "issuer_name": "Borrower C",
             "currency_value": 0, "report_date": "2023-03-31",
             "accession_number": "001"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=self._empty_bdc_df(), nport_df=nport_df)
        borrower = result[result["issuer_name"] == "Borrower C"]
        assert pd.isna(borrower.iloc[0]["cost"]) or borrower.iloc[0]["cost"] == 0


class TestSharesNormalization:
    """Tests for shares_held power-of-10 correction in build_unified_holdings."""

    def _make_nport_df(self, rows):
        """Build N-PORT DataFrame with all required columns."""
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def _empty_bdc_df(self):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        return pd.DataFrame({c: pd.Series(dtype=str) for c in cols})

    def _empty_nport_df(self):
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        return pd.DataFrame({c: pd.Series(dtype=str) for c in cols})

    def _make_bdc_df(self, rows):
        """Build BDC DataFrame with all required columns."""
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_1000x_outlier_corrected(self, tmp_path):
        """A single row with 1000x fewer shares is replaced with previous quarter."""
        # 4 periods, same position. Period 3 has shares=400 (should be 400000)
        nport_df = self._make_nport_df([
            {"cik": "100", "issuer_name": "Acme Corp", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 4000000,
             "report_date": "2023-03-31", "balance": "400000", "unit": "NS",
             "accession_number": "001"},
            {"cik": "100", "issuer_name": "Acme Corp", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 4100000,
             "report_date": "2023-06-30", "balance": "400000", "unit": "NS",
             "accession_number": "002"},
            {"cik": "100", "issuer_name": "Acme Corp", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 4200000,
             "report_date": "2023-09-30", "balance": "400", "unit": "NS",
             "accession_number": "003"},
            {"cik": "100", "issuer_name": "Acme Corp", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 4300000,
             "report_date": "2023-12-31", "balance": "400000", "unit": "NS",
             "accession_number": "004"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=self._empty_bdc_df(), nport_df=nport_df)
        acme = result[result["issuer_name"] == "Acme Corp"].sort_values("report_date")
        shares = acme["shares_held"].tolist()
        # Q3 outlier (400) replaced with Q2's shares (400000)
        assert shares == [400000.0, 400000.0, 400000.0, 400000.0]

    def test_consistent_shares_unchanged(self, tmp_path):
        """Positions with consistent shares are not modified."""
        nport_df = self._make_nport_df([
            {"cik": "100", "issuer_name": "Stable Co", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 5000000,
             "report_date": "2023-03-31", "balance": "50000", "unit": "NS",
             "accession_number": "001"},
            {"cik": "100", "issuer_name": "Stable Co", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 5100000,
             "report_date": "2023-06-30", "balance": "50000", "unit": "NS",
             "accession_number": "002"},
            {"cik": "100", "issuer_name": "Stable Co", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 5200000,
             "report_date": "2023-09-30", "balance": "50000", "unit": "NS",
             "accession_number": "003"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=self._empty_bdc_df(), nport_df=nport_df)
        stable = result[result["issuer_name"] == "Stable Co"]
        assert (stable["shares_held"] == 50000.0).all()

    def test_two_observations_corrected(self, tmp_path):
        """With 2 obs, outlier shares replaced with neighbor's shares."""
        # Q1 correct (shares=1000), Q2 outlier (shares=5000000, i.e. $5M)
        nport_df = self._make_nport_df([
            {"cik": "100", "issuer_name": "TwoObs", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 5000000,
             "report_date": "2023-03-31", "balance": "1000", "unit": "NS",
             "accession_number": "001"},
            {"cik": "100", "issuer_name": "TwoObs", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 5000000,
             "report_date": "2023-06-30", "balance": "5000000", "unit": "NS",
             "accession_number": "002"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=self._empty_bdc_df(), nport_df=nport_df)
        obs = result[result["issuer_name"] == "TwoObs"].sort_values("report_date")
        shares = obs["shares_held"].tolist()
        # Q1 unchanged, Q2 outlier replaced with Q1's shares (1000)
        assert shares[0] == 1000.0
        assert shares[1] == 1000.0

    def test_single_observation_skipped(self, tmp_path):
        """With only 1 observation, no correction is applied (need >= 2)."""
        nport_df = self._make_nport_df([
            {"cik": "100", "issuer_name": "OneObs", "asset_cat": "EC",
             "issuer_type": "CORP", "currency_value": 1000000,
             "report_date": "2023-03-31", "balance": "10", "unit": "NS",
             "accession_number": "001"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=self._empty_bdc_df(), nport_df=nport_df)
        obs = result[result["issuer_name"] == "OneObs"]
        assert obs.iloc[0]["shares_held"] == 10.0

    def test_null_shares_passthrough(self, tmp_path):
        """Rows with NULL shares_held pass through unchanged."""
        nport_df = self._make_nport_df([
            {"cik": "100", "issuer_name": "NoShares", "asset_cat": "LON",
             "issuer_type": "CORP", "currency_value": 500000,
             "report_date": "2023-03-31",
             "accession_number": "001"},
            {"cik": "100", "issuer_name": "NoShares", "asset_cat": "LON",
             "issuer_type": "CORP", "currency_value": 510000,
             "report_date": "2023-06-30",
             "accession_number": "002"},
            {"cik": "100", "issuer_name": "NoShares", "asset_cat": "LON",
             "issuer_type": "CORP", "currency_value": 520000,
             "report_date": "2023-09-30",
             "accession_number": "003"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=self._empty_bdc_df(), nport_df=nport_df)
        noshares = result[result["issuer_name"] == "NoShares"]
        assert noshares["shares_held"].isna().all()

    def test_bdc_shares_corrected(self, tmp_path):
        """BDC shares with 1000x outlier replaced with previous quarter."""
        bdc_df = self._make_bdc_df([
            {"cik": "200", "investment_identifier": "Widget Inc - Common Equity",
             "fair_value": 2000000, "shares_held": "200000",
             "report_date": "2023-03-31", "accession_number": "001"},
            {"cik": "200", "investment_identifier": "Widget Inc - Common Equity",
             "fair_value": 2100000, "shares_held": "200000",
             "report_date": "2023-06-30", "accession_number": "002"},
            {"cik": "200", "investment_identifier": "Widget Inc - Common Equity",
             "fair_value": 2200000, "shares_held": "200",
             "report_date": "2023-09-30", "accession_number": "003"},
            {"cik": "200", "investment_identifier": "Widget Inc - Common Equity",
             "fair_value": 2300000, "shares_held": "200000",
             "report_date": "2023-12-31", "accession_number": "004"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=bdc_df, nport_df=self._empty_nport_df())
        widget = result[result["issuer_name"].str.contains("Widget", na=False)].sort_values("report_date")
        shares = widget["shares_held"].tolist()
        # Q3 outlier (200) replaced with Q2's shares (200000)
        assert shares == [200000.0, 200000.0, 200000.0, 200000.0]


# ---------------------------------------------------------------------------
# 3-pipe format detection: company-first and company-seg2
# ---------------------------------------------------------------------------

class TestThreePipeFormatDetection:
    """Tests for distinguishing 3-pipe sub-formats via legal suffix and
    instrument keyword heuristics in the SQL path."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    # -- company_first: Company | Industry | Instrument --

    def test_company_first_inc(self):
        """CP Energy Services Inc. | Industry | First Lien Term Loan -> issuer = seg1."""
        df = self._make_bdc_df([{
            "investment_identifier": "CP Energy Services Inc. | Energy Equipment & Services | First Lien Term Loan",
            "cik": "1287032", "fair_value": 5000000, "interest_rate": 0.10,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "CP Energy Services Inc."
        assert result.iloc[0]["instrument_description"] == "First Lien Term Loan"

    def test_company_first_llc(self):
        """Belnick, LLC (d/b/a ...) | Industry | Instrument -> issuer = seg1."""
        df = self._make_bdc_df([{
            "investment_identifier": "Belnick, LLC (d/b/a The Ubique Group) | Household Durables | Preferred Class P Units",
            "cik": "1287032", "fair_value": 3000000, "interest_rate": 0.08,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Belnick, LLC (d/b/a The Ubique Group)"
        assert result.iloc[0]["instrument_description"] == "Preferred Class P Units"

    def test_company_first_corp(self):
        """OneTouchPoint Corp | Industry | Instrument."""
        df = self._make_bdc_df([{
            "investment_identifier": "OneTouchPoint Corp | Commercial Services | First Lien Term Loan",
            "cik": "1287032", "fair_value": 2000000, "interest_rate": 0.09,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "OneTouchPoint Corp"
        assert result.iloc[0]["instrument_description"] == "First Lien Term Loan"

    # -- company_seg2: Category | Company | Instrument --

    def test_company_seg2_affiliate_security(self):
        """Affiliated Entity | Company LLC | Preferred Stock -> issuer = seg2.

        Note: 'Non-Controlled Affiliate Security' is caught by the
        aggregate filter ('non-control' pattern), so we use
        'Affiliated Entity' which passes the filter.
        """
        df = self._make_bdc_df([{
            "investment_identifier": "Affiliated Entity | AGY Equity, LLC | Class B Preferred Stock",
            "cik": "999", "fair_value": 1000000, "shares_held": "100",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "AGY Equity, LLC"
        assert result.iloc[0]["instrument_description"] == "Class B Preferred Stock"

    def test_company_seg2_controlled_affiliate(self):
        """Controlled Affiliate Security | Gordon Brothers Finance Company | Unsecured Debt."""
        df = self._make_bdc_df([{
            "investment_identifier": "Controlled Affiliate Security | Gordon Brothers Finance Company | Unsecured Debt",
            "cik": "999", "fair_value": 2000000, "interest_rate": 0.07,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Gordon Brothers Finance Company"
        assert result.iloc[0]["instrument_description"] == "Unsecured Debt"

    def test_company_seg2_us_investment_companies(self):
        """U.S. Investment Companies | Fund L.P | LP Interests."""
        df = self._make_bdc_df([{
            "investment_identifier": "U.S. Investment Companies | Orangewood WWB Co-Invest L.P | LP Interests",
            "cik": "999", "fair_value": 500000, "shares_held": "50",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Orangewood WWB Co-Invest L.P"
        assert result.iloc[0]["instrument_description"] == "LP Interests"

    def test_company_seg2_affiliated_entity(self):
        """Affiliated Entity | Company LLC | Senior Secured Loans."""
        df = self._make_bdc_df([{
            "investment_identifier": "Affiliated Entity | Summit Professional Education, LLC | Senior Secured Loans",
            "cik": "999", "fair_value": 3000000, "interest_rate": 0.11,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Summit Professional Education, LLC"

    # -- SLR format (existing, should still work) --

    def test_slr_3_pipe_unchanged(self):
        """Common Stocks | Financials | American Banknote Corp. -> seg3."""
        df = self._make_bdc_df([{
            "investment_identifier": "Common Stocks | Financials | American Banknote Corp.",
            "cik": "999", "fair_value": 1000000, "shares_held": "1000",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "American Banknote Corp."
        assert "Common Stocks" in result.iloc[0]["instrument_description"]

    def test_slr_4_pipe_unchanged(self):
        """Type | Industry | Company | Instrument -> seg3."""
        df = self._make_bdc_df([{
            "investment_identifier": "Senior Secured Loans | Technology | Acme Corp | First Lien",
            "cik": "1418076", "fair_value": 1000000, "interest_rate": 0.10,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    # -- Affiliation-last format (existing, should still work) --

    def test_affil_last_unchanged(self):
        """Company | Instrument | Non-Affiliated Issuer -> seg1."""
        df = self._make_bdc_df([{
            "investment_identifier": "Blue Owl Capital | Senior Secured Loan | Non-Affiliated Issuer",
            "cik": "123", "fair_value": 5000000, "interest_rate": 0.10,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Blue Owl Capital"
        assert result.iloc[0]["instrument_description"] == "Senior Secured Loan"

    # -- Edge cases --

    def test_senior_loans_compound_seg3_stays_slr(self):
        """Senior loans % | Industry % | Company, Instrument(...) -> seg3 (SLR default).

        Even though seg3 contains instrument keywords, seg2 has no legal
        suffix so it does NOT match company_seg2 format.
        """
        df = self._make_bdc_df([{
            "investment_identifier": "Senior loans 195.4% | Commercial services 12.4% | BCTS Parent LLC, Term Loan",
            "cik": "999", "fair_value": 2000000, "interest_rate": 0.09,
        }])
        result = _prepare_bdc(df)
        # seg3 is compound "Company, Instrument" -- picked as issuer via SLR default
        assert "BCTS Parent LLC" in result.iloc[0]["issuer_name"]

    def test_llc_interests_not_company_first(self):
        """'LLC Interests | Real Estate | NexPoint Capital REIT LLC' -> SLR (seg3).

        seg1='LLC Interests' contains 'LLC' but NOT as a legal suffix at
        end-of-string, so it should NOT be detected as company-first.
        """
        df = self._make_bdc_df([{
            "investment_identifier": "LLC Interests | Real Estate | NexPoint Capital REIT LLC",
            "cik": "999", "fair_value": 1000000, "shares_held": "500",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "NexPoint Capital REIT LLC"

    def test_company_first_no_suffix_with_industry_label(self):
        """'Rosa Mexicano | Hotels, Restaurants & Leisure | First Lien Term Loan'.

        seg1 has no legal suffix, but seg3 is an instrument keyword and
        seg2 is a known industry label -> company_first via industry fallback.
        """
        df = self._make_bdc_df([{
            "investment_identifier": "Rosa Mexicano | Hotels, Restaurants & Leisure | First Lien Term Loan",
            "cik": "1287032", "fair_value": 1000000, "interest_rate": 0.09,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Rosa Mexicano"
        assert result.iloc[0]["instrument_description"] == "First Lien Term Loan"

    def test_company_first_no_suffix_kickapoo(self):
        """Kickapoo Ranch Pet Resort | Diversified Consumer Services | First Lien Term Loan."""
        df = self._make_bdc_df([{
            "investment_identifier": "Kickapoo Ranch Pet Resort | Diversified Consumer Services | First Lien Term Loan",
            "cik": "1287032", "fair_value": 500000, "interest_rate": 0.08,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["issuer_name"] == "Kickapoo Ranch Pet Resort"
        assert result.iloc[0]["instrument_description"] == "First Lien Term Loan"


# ---------------------------------------------------------------------------
# _enforce_schema
# ---------------------------------------------------------------------------

def _make_valid_row(**overrides):
    """Build a single-row DataFrame that passes all schema checks."""
    row = {
        "source": "bdc",
        "cik": "0001234567",
        "entity_name": "Test BDC",
        "accession_number": "0001234567-24-000001",
        "filing_date": "2024-03-15",
        "report_date": "2024-03-31",
        "issuer_name": "Acme Corp",
        "instrument_description": "First Lien Term Loan",
        "cusip": "",
        "isin": "",
        "lei": "",
        "ticker": "",
        "fair_value": 1000000.0,
        "cost": 990000.0,
        "pct_of_net_assets": 2.5,
        "shares_held": "",
        "principal_amount": 1000000.0,
        "asset_category": "LOAN",
        "issuer_category": "CORPORATE",
        "index_classification": "DIRECT_LENDING",
        "exposure_type": "DIRECT",
        "asset_class": "PRIVATE_CREDIT",
        "fair_value_level": "",
        "interest_rate": 10.5,
        "basis_spread": 5.5,
        "reference_rate_type": "SOFR",
        "coupon_type": "Floating",
        "pik_rate": "",
        "maturity_date": "2027-06-30",
        "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
        "bdc_form_type": "10-K",
        "bdc_dimensions_raw": "",
        "bdc_unrealized_gain_loss": "",
        "nport_holding_id": "",
        "nport_series_name": "",
        "nport_series_id": "",
        "nport_asset_cat": "",
        "nport_issuer_type": "",
        "nport_payoff_profile": "",
        "nport_investment_country": "",
        "nport_is_restricted": "",
        "nport_quarter": "",
        "nport_is_default": "",
        "nport_are_interest_payments_in_arrears": "",
        "nport_is_paid_in_kind": "",
        "nport_currency_code": "",
        "nport_liquidity_classification": "",
        "entity_id": "",
        "canonical_name": "",
        "extracted_industry": "",
        "position_id": "",
    }
    row.update(overrides)
    return pd.DataFrame([row])


class TestEnforceSchema:
    """Tests for _enforce_schema()."""

    def test_clean_passes_all_checks(self):
        df = _make_valid_row()
        violations = _enforce_schema(df)
        assert violations == []

    def test_empty_dataframe_passes(self):
        df = pd.DataFrame()
        violations = _enforce_schema(df)
        assert violations == []

    def test_bad_cik_length(self):
        df = _make_valid_row(cik="12345")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "cik_format" in names

    def test_bad_cik_alpha(self):
        df = _make_valid_row(cik="000123456A")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "cik_format" in names

    def test_bad_source(self):
        df = _make_valid_row(source="xbrl")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "source_enum" in names

    def test_bad_asset_category(self):
        df = _make_valid_row(asset_category="BOND")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "asset_category_enum" in names

    def test_bad_index_classification(self):
        df = _make_valid_row(index_classification="DIRECT_EQUITY")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "index_classification_enum" in names

    def test_unparseable_report_date(self):
        df = _make_valid_row(report_date="not-a-date")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "report_date_parseable" in names

    def test_null_fair_value(self):
        """NaN in pandas becomes NULL in DuckDB -- should be caught."""
        df = _make_valid_row(fair_value=float("nan"))
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "fair_value_is_null" in names

    def test_none_fair_value(self):
        df = _make_valid_row(fair_value=None)
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "fair_value_is_null" in names

    def test_bad_coupon_type(self):
        df = _make_valid_row(coupon_type="Variable")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "coupon_type_enum" in names

    def test_interest_rate_too_high(self):
        df = _make_valid_row(interest_rate=60.0)
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "interest_rate_range" in names

    def test_interest_rate_negative(self):
        df = _make_valid_row(interest_rate=-1.0)
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "interest_rate_range" in names

    def test_basis_spread_too_high(self):
        df = _make_valid_row(basis_spread=35.0)
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "basis_spread_range" in names

    def test_pik_rate_too_high(self):
        df = _make_valid_row(pik_rate=30.0)
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "pik_rate_range" in names

    def test_pct_net_assets_extreme(self):
        df = _make_valid_row(pct_of_net_assets=200.0)
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "pct_net_assets_range" in names

    def test_negative_shares(self):
        df = _make_valid_row(shares_held=-100.0)
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "shares_not_negative" in names

    def test_negative_principal(self):
        df = _make_valid_row(principal_amount=-500000.0)
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "principal_not_negative" in names

    def test_bdc_missing_identifier(self):
        df = _make_valid_row(bdc_investment_identifier="")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "bdc_has_identifier" in names

    def test_dl_wrong_asset_category(self):
        """DIRECT_LENDING with asset_category=EQUITY_COMMON is a violation."""
        df = _make_valid_row(
            index_classification="DIRECT_LENDING",
            asset_category="EQUITY_COMMON",
        )
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "dl_implies_loan_or_debt_corporate" in names

    def test_dl_wrong_issuer_category(self):
        """DIRECT_LENDING with issuer_category=FUND is a violation."""
        df = _make_valid_row(
            index_classification="DIRECT_LENDING",
            asset_category="LOAN",
            issuer_category="FUND",
        )
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "dl_implies_loan_or_debt_corporate" in names

    def test_fund_index_wrong_issuer(self):
        """PRIVATE_CREDIT_FUND with issuer_category=CORPORATE is a violation."""
        df = _make_valid_row(
            index_classification="PRIVATE_CREDIT_FUND",
            issuer_category="CORPORATE",
            asset_category="FUND",
        )
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "fund_index_implies_fund_issuer" in names

    def test_nport_no_identifier_ok(self):
        """N-PORT rows don't need bdc_investment_identifier."""
        df = _make_valid_row(
            source="nport",
            bdc_investment_identifier="",
            bdc_form_type="",
        )
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "bdc_has_identifier" not in names

    def test_valid_boundary_values(self):
        """Boundary values that should pass: rate=50, spread=30, pik=25."""
        df = _make_valid_row(interest_rate=50.0, basis_spread=30.0, pik_rate=25.0)
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "interest_rate_range" not in names
        assert "basis_spread_range" not in names
        assert "pik_rate_range" not in names

    def test_multiple_violations(self):
        """A row with multiple problems produces multiple violations."""
        df = _make_valid_row(
            cik="123",
            source="unknown",
            interest_rate=99.0,
        )
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert len(violations) >= 3
        assert "cik_format" in names
        assert "source_enum" in names
        assert "interest_rate_range" in names


# ---------------------------------------------------------------------------
# 2-Axis Classification Tests
# ---------------------------------------------------------------------------

def _sql_classify(rows):
    """Helper: run exposure_type and asset_class SQL classification on test rows.

    Each row is a dict with keys: asset_category, issuer_category,
    issuer_name, instrument_description, nport_issuer_type (optional).
    Returns list of (exposure_type, asset_class) tuples.
    """
    import duckdb

    cols = ["asset_category", "issuer_category", "issuer_name",
            "instrument_description", "nport_issuer_type", "nport_asset_cat"]
    data = []
    for r in rows:
        data.append({c: r.get(c, "") for c in cols})
    df = pd.DataFrame(data)

    con = duckdb.connect()
    con.register("t", df)

    # Precompute _combined_fund_text (same as build_unified_holdings)
    con.execute("""
        CREATE TABLE test_data AS
        SELECT *,
            COALESCE(lower(trim(issuer_name)), '') || ' ' ||
            COALESCE(lower(trim(instrument_description)), '') AS _combined_fund_text
        FROM t
    """)

    exp_sql = _sql_classify_exposure_type()
    ac_sql = _sql_classify_asset_class()

    results = con.execute(f"""
        SELECT {exp_sql} AS exposure_type, {ac_sql} AS asset_class
        FROM test_data
    """).fetchall()
    con.close()
    return results


class TestExposureType:
    """Tests for _sql_classify_exposure_type."""

    def test_direct_corporate_loan(self):
        result = _sql_classify([
            {"asset_category": "LOAN", "issuer_category": "CORPORATE",
             "issuer_name": "Acme Corp", "instrument_description": "First Lien"}
        ])
        assert result[0][0] == "DIRECT"

    def test_direct_corporate_equity(self):
        result = _sql_classify([
            {"asset_category": "EQUITY_COMMON", "issuer_category": "CORPORATE",
             "issuer_name": "Tech Holdings Inc", "instrument_description": "Common Stock"}
        ])
        assert result[0][0] == "DIRECT"

    def test_fund_issuer_category(self):
        result = _sql_classify([
            {"asset_category": "FUND", "issuer_category": "FUND",
             "issuer_name": "Blackstone PE Fund III", "instrument_description": ""}
        ])
        assert result[0][0] == "FUND"

    def test_liquid_government(self):
        result = _sql_classify([
            {"asset_category": "DEBT", "issuer_category": "GOVERNMENT",
             "issuer_name": "US Treasury Note", "instrument_description": ""}
        ])
        assert result[0][0] == "LIQUID"

    def test_liquid_cash_keyword(self):
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "OTHER",
             "issuer_name": "Financial Square Money Market Fund",
             "instrument_description": ""}
        ])
        assert result[0][0] == "LIQUID"

    def test_liquid_treasury_keyword(self):
        result = _sql_classify([
            {"asset_category": "DEBT", "issuer_category": "CORPORATE",
             "issuer_name": "U.S. Treasury Bills",
             "instrument_description": "T-Bill 3M"}
        ])
        assert result[0][0] == "LIQUID"

    def test_fund_via_issuer_category(self):
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "Millennium International Ltd.",
             "instrument_description": ""}
        ])
        assert result[0][0] == "FUND"

    def test_direct_other_corporate(self):
        """OTHER asset + CORPORATE issuer -> DIRECT (not FUND/LIQUID)."""
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "CORPORATE",
             "issuer_name": "Widget Corp", "instrument_description": "Warrant"}
        ])
        assert result[0][0] == "DIRECT"

    def test_direct_not_triggered_by_property_corporate(self):
        """'National Property Solutions LLC' is CORPORATE -> DIRECT (not LIQUID/FUND)."""
        result = _sql_classify([
            {"asset_category": "LOAN", "issuer_category": "CORPORATE",
             "issuer_name": "National Property Solutions LLC",
             "instrument_description": "First Lien Term Loan"}
        ])
        assert result[0][0] == "DIRECT"


class TestAssetClass:
    """Tests for _sql_classify_asset_class."""

    def test_private_credit_loan_corporate(self):
        result = _sql_classify([
            {"asset_category": "LOAN", "issuer_category": "CORPORATE",
             "issuer_name": "Acme Corp", "instrument_description": "Senior Secured"}
        ])
        assert result[0][1] == "PRIVATE_CREDIT"

    def test_private_credit_debt_corporate(self):
        result = _sql_classify([
            {"asset_category": "DEBT", "issuer_category": "CORPORATE",
             "issuer_name": "Widget Inc", "instrument_description": "Unsecured Note"}
        ])
        assert result[0][1] == "PRIVATE_CREDIT"

    def test_private_equity_common_corporate(self):
        result = _sql_classify([
            {"asset_category": "EQUITY_COMMON", "issuer_category": "CORPORATE",
             "issuer_name": "Tech Holdings Inc", "instrument_description": "Common Stock"}
        ])
        assert result[0][1] == "PRIVATE_EQUITY"

    def test_private_equity_preferred_corporate(self):
        result = _sql_classify([
            {"asset_category": "EQUITY_PREFERRED", "issuer_category": "CORPORATE",
             "issuer_name": "Startup Inc", "instrument_description": "Series A Preferred"}
        ])
        assert result[0][1] == "PRIVATE_EQUITY"

    def test_private_equity_fund_pe_signals(self):
        result = _sql_classify([
            {"asset_category": "FUND", "issuer_category": "FUND",
             "issuer_name": "Blackstone Private Equity Partners VIII",
             "instrument_description": ""}
        ])
        assert result[0][1] == "PRIVATE_EQUITY"

    def test_private_credit_fund_credit_signals(self):
        result = _sql_classify([
            {"asset_category": "FUND", "issuer_category": "FUND",
             "issuer_name": "Apollo Senior Credit Fund III",
             "instrument_description": ""}
        ])
        assert result[0][1] == "PRIVATE_CREDIT"

    def test_real_estate_reit_keyword(self):
        result = _sql_classify([
            {"asset_category": "FUND", "issuer_category": "FUND",
             "issuer_name": "Blackstone Real Estate Partners",
             "instrument_description": ""}
        ])
        assert result[0][1] == "REAL_ESTATE"

    def test_real_estate_fund_only_property(self):
        """'property' keyword only triggers RE when issuer_category=FUND."""
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "National Property Trust",
             "instrument_description": ""}
        ])
        assert result[0][1] == "REAL_ESTATE"

    def test_property_corporate_not_real_estate(self):
        """'National Property Solutions LLC' (CORPORATE) should NOT be REAL_ESTATE.
        LOAN+CORPORATE -> PRIVATE_CREDIT takes priority."""
        result = _sql_classify([
            {"asset_category": "LOAN", "issuer_category": "CORPORATE",
             "issuer_name": "National Property Solutions LLC",
             "instrument_description": "First Lien Term Loan"}
        ])
        assert result[0][1] == "PRIVATE_CREDIT"

    def test_structured_credit_clo(self):
        result = _sql_classify([
            {"asset_category": "DEBT", "issuer_category": "CORPORATE",
             "issuer_name": "Barings CLO Ltd 2024-1",
             "instrument_description": "CLO Senior Notes"}
        ])
        assert result[0][1] == "STRUCTURED_CREDIT"

    def test_structured_credit_loan_note_issuer(self):
        result = _sql_classify([
            {"asset_category": "DEBT", "issuer_category": "CORPORATE",
             "issuer_name": "MidOcean Credit CLO Loan Note Issuer",
             "instrument_description": ""}
        ])
        assert result[0][1] == "STRUCTURED_CREDIT"

    def test_cash_government(self):
        result = _sql_classify([
            {"asset_category": "DEBT", "issuer_category": "GOVERNMENT",
             "issuer_name": "U.S. Treasury Bond",
             "instrument_description": ""}
        ])
        assert result[0][1] == "CASH"

    def test_cash_money_market_keyword(self):
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "OTHER",
             "issuer_name": "Goldman Sachs Financial Square Money Market Fund",
             "instrument_description": ""}
        ])
        assert result[0][1] == "CASH"

    def test_fund_no_signals_other(self):
        """Fund with no credit/PE signals -> OTHER (asset_class)."""
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "Millennium International Ltd.",
             "instrument_description": ""}
        ])
        assert result[0][1] == "OTHER"

    def test_hedge_fund_explicit_keyword(self):
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "Citadel Multi-Strategy Fund",
             "instrument_description": ""}
        ])
        assert result[0][1] == "HEDGE_FUND"

    def test_other_fallback(self):
        """OTHER asset + OTHER issuer with no keywords -> OTHER."""
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "OTHER",
             "issuer_name": "Unknown Entity ABC",
             "instrument_description": ""}
        ])
        assert result[0][1] == "OTHER"

    # -- nport_asset_cat refinement (SQL-level) --

    def test_nac_ec_fund_pe_sql(self):
        """FUND + nport_asset_cat=EC -> PRIVATE_EQUITY (not HEDGE_FUND)."""
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "Bain Capital Fund VII L.P.",
             "instrument_description": "", "nport_asset_cat": "EC"}
        ])
        assert result[0][1] == "PRIVATE_EQUITY"

    def test_nac_re_fund_re_sql(self):
        """FUND + nport_asset_cat=RE -> REAL_ESTATE."""
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "IQHQ Inc.",
             "instrument_description": "", "nport_asset_cat": "RE"}
        ])
        assert result[0][1] == "REAL_ESTATE"

    def test_nac_dbt_fund_pc_sql(self):
        """FUND + nport_asset_cat=DBT -> PRIVATE_CREDIT."""
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "IQHQ Notes 12%",
             "instrument_description": "", "nport_asset_cat": "DBT"}
        ])
        assert result[0][1] == "PRIVATE_CREDIT"

    def test_nac_other_vintage_pe_sql(self):
        """FUND + nport_asset_cat=OTHER + vintage series -> PRIVATE_EQUITY."""
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "KKR European Fund V",
             "instrument_description": "", "nport_asset_cat": "OTHER"}
        ])
        assert result[0][1] == "PRIVATE_EQUITY"

    def test_nac_credit_keyword_wins_over_nac_ec_sql(self):
        """Credit keyword takes priority over nport_asset_cat=EC."""
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "Apollo Senior Credit Fund",
             "instrument_description": "", "nport_asset_cat": "EC"}
        ])
        assert result[0][1] == "PRIVATE_CREDIT"


class TestExpandedIndexClassification:
    """Tests for new index_classification values."""

    def test_real_estate_fund(self):
        result = _classify_index("FUND", "FUND", "Blackstone Real Estate Trust", "")
        assert result == "REAL_ESTATE_FUND"

    def test_real_estate_fund_property_keyword(self):
        result = _classify_index("FUND", "FUND", "Prologis Logistics Fund", "")
        assert result == "REAL_ESTATE_FUND"

    def test_structured_credit_clo_fund(self):
        """CLO with FUND issuer -> STRUCTURED_CREDIT (before credit fund)."""
        result = _classify_index("FUND", "FUND", "Barings CLO Ltd 2024-1", "")
        assert result == "STRUCTURED_CREDIT"

    def test_structured_credit_clo_other(self):
        """CLO with OTHER category -> STRUCTURED_CREDIT."""
        result = _classify_index("OTHER", "OTHER", "Barings CLO Ltd 2024-1", "")
        assert result == "STRUCTURED_CREDIT"

    def test_structured_credit_wins_over_direct_lending(self):
        """CLO keyword fires before DIRECT_LENDING (SC has highest priority)."""
        result = _classify_index("DEBT", "CORPORATE", "Barings CLO Ltd", "")
        assert result == "STRUCTURED_CREDIT"

    def test_fund_no_signals_unclassified(self):
        result = _classify_index("FUND", "FUND", "ABC Partners", "")
        assert result == "UNCLASSIFIED"

    def test_hedge_fund_explicit_keyword(self):
        result = _classify_index("OTHER", "FUND", "Citadel Multi-Strategy Fund", "")
        assert result == "HEDGE_FUND"

    # -- nport_asset_cat refinement (Fix 1) --

    def test_nac_ec_fund_becomes_pe_fund(self):
        """FUND + nport_asset_cat=EC -> PRIVATE_EQUITY_FUND (not HEDGE_FUND)."""
        result = _classify_index("OTHER", "FUND", "Bain Capital Fund VII L.P.", "",
                                 nport_asset_cat="EC")
        assert result == "PRIVATE_EQUITY_FUND"

    def test_nac_ep_fund_becomes_pe_fund(self):
        """FUND + nport_asset_cat=EP -> PRIVATE_EQUITY_FUND."""
        result = _classify_index("OTHER", "FUND", "Silver Cup Holdings V L.P.", "",
                                 nport_asset_cat="EP")
        assert result == "PRIVATE_EQUITY_FUND"

    def test_nac_re_fund_becomes_re_fund(self):
        """FUND + nport_asset_cat=RE -> REAL_ESTATE_FUND (not HEDGE_FUND)."""
        result = _classify_index("OTHER", "FUND", "IQHQ Inc.", "",
                                 nport_asset_cat="RE")
        assert result == "REAL_ESTATE_FUND"

    def test_nac_dbt_fund_becomes_pc_fund(self):
        """FUND + nport_asset_cat=DBT -> PRIVATE_CREDIT_FUND."""
        result = _classify_index("OTHER", "FUND", "IQHQ Notes 12%", "",
                                 nport_asset_cat="DBT")
        assert result == "PRIVATE_CREDIT_FUND"

    def test_nac_lon_fund_becomes_pc_fund(self):
        """FUND + nport_asset_cat=LON -> PRIVATE_CREDIT_FUND."""
        result = _classify_index("OTHER", "FUND", "Some Loan Fund", "",
                                 nport_asset_cat="LON")
        assert result == "PRIVATE_CREDIT_FUND"

    def test_nac_other_vintage_pe_fund(self):
        """FUND + nport_asset_cat=OTHER + vintage series -> PRIVATE_EQUITY_FUND."""
        result = _classify_index("OTHER", "FUND", "KKR European Fund V", "",
                                 nport_asset_cat="OTHER")
        assert result == "PRIVATE_EQUITY_FUND"

    def test_nac_keyword_still_wins_over_nac(self):
        """Credit keyword signal takes priority over nport_asset_cat=EC."""
        result = _classify_index("OTHER", "FUND", "Apollo Senior Credit Fund", "",
                                 nport_asset_cat="EC")
        assert result == "PRIVATE_CREDIT_FUND"

    def test_nac_pe_keyword_wins_over_nac_dbt(self):
        """PE keyword signal takes priority over nport_asset_cat=DBT."""
        result = _classify_index("OTHER", "FUND", "Growth Equity Partners", "",
                                 nport_asset_cat="DBT")
        assert result == "PRIVATE_EQUITY_FUND"

    def test_direct_real_estate_corporate(self):
        """CORPORATE + RE keywords (not LOAN/DEBT) -> DIRECT_REAL_ESTATE."""
        result = _classify_index("OTHER", "CORPORATE", "PRISA Real Estate Fund", "")
        assert result == "DIRECT_REAL_ESTATE"

    def test_cash_government(self):
        result = _classify_index("DEBT", "GOVERNMENT", "U.S. Treasury", "")
        assert result == "CASH"

    def test_cash_keyword_nongovernment(self):
        result = _classify_index("OTHER", "OTHER", "Financial Square Money Market Fund", "")
        assert result == "CASH"

    def test_existing_direct_lending_unchanged(self):
        result = _classify_index("LOAN", "CORPORATE", "Acme Corp", "First Lien TL")
        assert result == "DIRECT_LENDING"

    def test_existing_common_equity_unchanged(self):
        result = _classify_index("EQUITY_COMMON", "CORPORATE", "Tech Inc", "Common")
        assert result == "COMMON_EQUITY"

    def test_existing_preferred_equity_unchanged(self):
        result = _classify_index("EQUITY_PREFERRED", "CORPORATE", "Startup", "Pref")
        assert result == "PREFERRED_EQUITY"

    def test_existing_credit_fund_unchanged(self):
        result = _classify_index("FUND", "FUND", "Direct Lending Partners", "")
        assert result == "PRIVATE_CREDIT_FUND"

    def test_existing_pe_fund_unchanged(self):
        result = _classify_index("FUND", "FUND", "Growth Equity Partners", "")
        assert result == "PRIVATE_EQUITY_FUND"

    # -- P1 regression: regular corporate loan still DIRECT_LENDING --

    def test_regular_corporate_loan_still_direct_lending(self):
        """LOAN+CORPORATE without CLO keyword -> DIRECT_LENDING."""
        result = _classify_index("LOAN", "CORPORATE", "Acme Holdings LLC", "Senior Secured First Lien")
        assert result == "DIRECT_LENDING"

    def test_clo_in_instrument_desc_structured_credit(self):
        """LOAN+CORPORATE but CLO in instrument_description -> STRUCTURED_CREDIT."""
        result = _classify_index("LOAN", "CORPORATE",
                                 "Barings CLO Ltd 2024-1",
                                 "Collateralized Loan Obligation")
        assert result == "STRUCTURED_CREDIT"

    # -- P3: hedge fund keyword additions --

    def test_hedge_fund_multi_strategy_no_hyphen(self):
        """FUND + 'multi strategy' (no hyphen) -> HEDGE_FUND."""
        result = _classify_index("OTHER", "FUND", "AQR Multi Strategy Fund LP", "")
        assert result == "HEDGE_FUND"

    def test_hedge_fund_absolute_return(self):
        """FUND + 'absolute return' -> HEDGE_FUND."""
        result = _classify_index("OTHER", "FUND", "Bridgewater Absolute Return Fund", "")
        assert result == "HEDGE_FUND"

    def test_hedge_fund_keyword_wins_over_nac_ec(self):
        """FUND + hedge keyword + nac=EC -> HEDGE_FUND (not PE)."""
        result = _classify_index("OTHER", "FUND", "Citadel Multi Strategy Fund", "",
                                 nport_asset_cat="EC")
        assert result == "HEDGE_FUND"


class TestEnforceSchemaNewColumns:
    """Tests for schema enforcement of new columns."""

    def test_valid_exposure_type(self):
        df = _make_valid_row(exposure_type="FUND")
        violations = _enforce_schema(df)
        assert violations == []

    def test_invalid_exposure_type(self):
        df = _make_valid_row(exposure_type="INDIRECT")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "exposure_type_enum" in names

    def test_valid_asset_class(self):
        df = _make_valid_row(asset_class="HEDGE_FUND")
        violations = _enforce_schema(df)
        assert violations == []

    def test_invalid_asset_class(self):
        df = _make_valid_row(asset_class="COMMODITIES")
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "asset_class_enum" in names

    def test_new_index_values_pass(self):
        """New index classification values pass schema check."""
        for val in ["REAL_ESTATE_FUND", "DIRECT_REAL_ESTATE",
                    "STRUCTURED_CREDIT", "HEDGE_FUND", "CASH"]:
            df = _make_valid_row(index_classification=val)
            violations = _enforce_schema(df)
            names = [v[0] for v in violations]
            assert "index_classification_enum" not in names, f"{val} should be valid"


# ---------------------------------------------------------------------------
# _stabilize_classification
# ---------------------------------------------------------------------------


def _make_stabilization_df(rows_spec):
    """Helper: create a DataFrame suitable for _stabilize_classification.

    rows_spec: list of (issuer_name, report_date, index_classification,
                        exposure_type, asset_class)
    All rows get cik='0001234567' and source='bdc' by default.
    """
    rows = []
    for issuer, rdate, ic, et, ac in rows_spec:
        row = {col: "" for col in UNIFIED_COLUMNS}
        row["cik"] = "0001234567"
        row["issuer_name"] = issuer
        row["report_date"] = rdate
        row["index_classification"] = ic
        row["exposure_type"] = et
        row["asset_class"] = ac
        row["source"] = "bdc"
        row["fair_value"] = "1000000"
        rows.append(row)
    return pd.DataFrame(rows)[UNIFIED_COLUMNS]


class TestStabilizeClassification:
    """Tests for QoQ classification stabilization (2x majority rule)."""

    def test_clear_majority_overrides_minority(self):
        """6 quarters DL, 1 quarter CE -> all become DL."""
        spec = [
            ("Acme Corp", f"2024-0{i+1}-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT")
            for i in range(6)
        ] + [
            ("Acme Corp", "2024-07-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY"),
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        assert (result["index_classification"] == "DIRECT_LENDING").all()
        assert (result["asset_class"] == "PRIVATE_CREDIT").all()

    def test_exact_tie_no_change(self):
        """4 quarters DL, 4 quarters CE -> no change (tie)."""
        spec = [
            ("Tied Corp", f"2024-0{i+1}-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT")
            for i in range(4)
        ] + [
            ("Tied Corp", f"2024-0{i+5}-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY")
            for i in range(4)
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        # First 4 should remain DL, last 4 should remain CE
        assert result.iloc[:4]["index_classification"].tolist() == ["DIRECT_LENDING"] * 4
        assert result.iloc[4:]["index_classification"].tolist() == ["COMMON_EQUITY"] * 4

    def test_majority_not_2x_no_change(self):
        """3 quarters DL, 2 quarters CE -> no change (3 < 2*2)."""
        spec = [
            ("Close Corp", f"2024-0{i+1}-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT")
            for i in range(3)
        ] + [
            ("Close Corp", f"2024-0{i+4}-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY")
            for i in range(2)
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        assert result.iloc[:3]["index_classification"].tolist() == ["DIRECT_LENDING"] * 3
        assert result.iloc[3:]["index_classification"].tolist() == ["COMMON_EQUITY"] * 2

    def test_single_quarter_no_change(self):
        """Position with only 1 quarter -> no change."""
        spec = [("Solo Corp", "2024-01-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY")]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        assert result.iloc[0]["index_classification"] == "COMMON_EQUITY"

    def test_never_changes_no_effect(self):
        """Position always DL -> no change (no second class)."""
        spec = [
            ("Stable Corp", f"2024-0{i+1}-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT")
            for i in range(5)
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        assert (result["index_classification"] == "DIRECT_LENDING").all()

    def test_pcf_to_ce_flip_stabilized(self):
        """OCIC SLF pattern: 6 quarters PCF, 1 quarter CE -> all PCF."""
        spec = [
            ("OCIC SLF LLC", f"2024-0{i+1}-31",
             "PRIVATE_CREDIT_FUND", "FUND", "PRIVATE_CREDIT")
            for i in range(6)
        ] + [
            ("OCIC SLF LLC", "2024-07-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY"),
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        assert (result["index_classification"] == "PRIVATE_CREDIT_FUND").all()
        assert (result["exposure_type"] == "FUND").all()
        assert (result["asset_class"] == "PRIVATE_CREDIT").all()

    def test_multiple_positions_independent(self):
        """Two positions in same CIK stabilized independently."""
        spec = [
            # Position A: 4:1 DL:CE -> stabilize to DL
            ("Pos A", f"2024-0{i+1}-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT")
            for i in range(4)
        ] + [
            ("Pos A", "2024-05-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY"),
        ] + [
            # Position B: 1:4 DL:CE -> stabilize to CE
            ("Pos B", "2024-01-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT"),
        ] + [
            ("Pos B", f"2024-0{i+2}-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY")
            for i in range(4)
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        a_rows = result[result["issuer_name"] == "Pos A"]
        b_rows = result[result["issuer_name"] == "Pos B"]
        assert (a_rows["index_classification"] == "DIRECT_LENDING").all()
        assert (b_rows["index_classification"] == "COMMON_EQUITY").all()

    def test_three_classes_majority_wins(self):
        """Position with 3 classifications: 6 DL, 2 CE, 1 PE -> DL wins (6 >= 2*2)."""
        spec = [
            ("Multi Corp", f"2024-0{i+1}-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT")
            for i in range(6)
        ] + [
            ("Multi Corp", "2024-07-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY"),
            ("Multi Corp", "2024-08-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY"),
            ("Multi Corp", "2024-09-30", "PREFERRED_EQUITY", "DIRECT", "PRIVATE_EQUITY"),
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        assert (result["index_classification"] == "DIRECT_LENDING").all()

    def test_empty_dataframe(self):
        """Empty DataFrame passes through without error."""
        df = pd.DataFrame(columns=UNIFIED_COLUMNS)
        result = _stabilize_classification(df)
        assert result.empty

    def test_boundary_exactly_2x(self):
        """Exactly 2x threshold: 4 quarters DL, 2 quarters CE -> stabilize (4 >= 2*2)."""
        spec = [
            ("Boundary Corp", f"2024-0{i+1}-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT")
            for i in range(4)
        ] + [
            ("Boundary Corp", f"2024-0{i+5}-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY")
            for i in range(2)
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        assert (result["index_classification"] == "DIRECT_LENDING").all()

    def test_boundary_just_below_2x(self):
        """Just below 2x: 3 quarters DL, 2 quarters CE -> no change (3 < 2*2)."""
        spec = [
            ("Below Corp", f"2024-0{i+1}-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT")
            for i in range(3)
        ] + [
            ("Below Corp", f"2024-0{i+4}-31", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY")
            for i in range(2)
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        # No stabilization: 3 < 4
        assert result.iloc[:3]["index_classification"].tolist() == ["DIRECT_LENDING"] * 3
        assert result.iloc[3:]["index_classification"].tolist() == ["COMMON_EQUITY"] * 2

    def test_column_order_preserved(self):
        """Output column order matches UNIFIED_COLUMNS."""
        spec = [
            ("Order Corp", f"2024-0{i+1}-31", "DIRECT_LENDING", "DIRECT", "PRIVATE_CREDIT")
            for i in range(3)
        ] + [
            ("Order Corp", "2024-04-30", "COMMON_EQUITY", "DIRECT", "PRIVATE_EQUITY"),
        ]
        df = _make_stabilization_df(spec)
        result = _stabilize_classification(df)
        assert list(result.columns) == UNIFIED_COLUMNS


# ---------------------------------------------------------------------------
# A1: Expanded aggregate pattern tests
# ---------------------------------------------------------------------------

class TestExpandedAggregatePatterns:
    """Tests for newly added _BDC_AGGREGATE_PATTERNS and _BDC_AGGREGATE_EXACT."""

    def test_investments_in_non_controlled(self):
        assert _is_bdc_aggregate_row(
            "Investments in Non-Controlled/Non-Affiliated Portfolio Companies"
        )

    def test_investments_in_non_affiliated(self):
        assert _is_bdc_aggregate_row("Investments in Non-Affiliated Issuers")

    def test_investments_in_affiliated(self):
        assert _is_bdc_aggregate_row("Investments in Affiliated Issuers")

    def test_first_lien_debt_exact(self):
        assert _is_bdc_aggregate_row("First Lien Debt")

    def test_second_lien_debt_exact(self):
        assert _is_bdc_aggregate_row("Second Lien Debt")

    def test_subordinated_debt_exact(self):
        assert _is_bdc_aggregate_row("Subordinated Debt")

    def test_mezzanine_debt_exact(self):
        assert _is_bdc_aggregate_row("Mezzanine Debt")

    def test_investments_debt_investments_exact(self):
        assert _is_bdc_aggregate_row("Investments Debt Investments")

    # Guard: real positions should NOT be filtered
    def test_real_position_with_lien_keyword_kept(self):
        assert not _is_bdc_aggregate_row(
            "Acme Corp - First Lien Term Loan"
        )

    def test_real_position_with_mezzanine_kept(self):
        assert not _is_bdc_aggregate_row(
            "Beta Holdings LLC - Mezzanine Debt - Due 12/15/2027"
        )


# ---------------------------------------------------------------------------
# A2: Bad issuer name filter tests
# ---------------------------------------------------------------------------

class TestIsBadIssuerName:
    """Tests for _is_bad_issuer_name Python mirror."""

    # Rule 1: exact match
    def test_exact_investments(self):
        assert _is_bad_issuer_name("Investments")

    def test_exact_debt_investments(self):
        assert _is_bad_issuer_name("Debt Investments")

    def test_exact_equity_securities(self):
        assert _is_bad_issuer_name("Equity Securities")

    def test_exact_cash(self):
        assert _is_bad_issuer_name("Cash")

    def test_exact_non_controlled(self):
        assert _is_bad_issuer_name("Non-Controlled")

    def test_exact_first_lien_debt(self):
        assert _is_bad_issuer_name("First Lien Debt")

    def test_exact_case_insensitive(self):
        assert _is_bad_issuer_name("INVESTMENTS")

    def test_exact_with_whitespace(self):
        assert _is_bad_issuer_name("  investments  ")

    # Rule 2: no alphabetic characters
    def test_date_only(self):
        assert _is_bad_issuer_name("01/15/2025")

    def test_percentage_only(self):
        assert _is_bad_issuer_name("1.00%")

    def test_number_only(self):
        assert _is_bad_issuer_name("12345")

    # Rule 3: bad prefix without entity signals
    def test_prefix_non_controlled_slash(self):
        assert _is_bad_issuer_name("Non-Controlled/Non-Affiliated Debt Investments")

    def test_prefix_investments_non_controlled(self):
        assert _is_bad_issuer_name("Investments Non-Controlled Portfolio")

    def test_prefix_with_entity_signal_kept(self):
        """Bad prefix but has entity signal (LLC) -> NOT filtered."""
        assert not _is_bad_issuer_name("Non-Controlled/Non-Affiliated Acme LLC")

    def test_prefix_with_holdings_signal_kept(self):
        assert not _is_bad_issuer_name(
            "Investments Non-Controlled Beta Holdings Corp."
        )

    # Guards: real companies should NOT be filtered
    def test_real_company_kept(self):
        assert not _is_bad_issuer_name("Acme Corp.")

    def test_real_company_with_llc_kept(self):
        assert not _is_bad_issuer_name("Total Safety Holdings LLC")

    def test_none_input(self):
        assert not _is_bad_issuer_name(None)

    def test_empty_string(self):
        assert not _is_bad_issuer_name("")


class TestBadIssuerNameInPrepareBdc:
    """Integration test: bad issuer names filtered in _prepare_bdc."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_filters_bare_investments_issuer(self):
        """Position with issuer_name='Investments' after extraction is removed."""
        df = self._make_bdc_df([
            # This will parse to issuer_name="Investments" (bare category)
            {"investment_identifier": "Investments",
             "cik": "123", "fair_value": 50000000},
            {"investment_identifier": "Acme Corp - Term Loan",
             "cik": "123", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        # "Investments" should be caught by both aggregate filter AND bad issuer
        assert len(result) == 1
        assert "Acme" in result.iloc[0]["issuer_name"]

    def test_keeps_real_company_through_bad_issuer_filter(self):
        """Real company names with entity signals survive the filter."""
        df = self._make_bdc_df([
            {"investment_identifier": "Investment Corp. - First Lien Term Loan",
             "cik": "123", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# A3: N-PORT negative FV filter tests
# ---------------------------------------------------------------------------

class TestNportNegativeFvFilter:
    """Tests for negative fair_value and NULL fair_value filtering in _prepare_nport."""

    def _make_nport_df(self, rows):
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "currency_value", "percentage",
            "asset_cat", "issuer_type", "investment_country",
            "is_restricted_security", "fair_value_level", "maturity_date",
            "coupon_type", "annualized_rate", "identifier_isin",
            "identifier_ticker", "payoff_profile", "cik", "registrant_name",
            "filing_date", "report_date", "series_name", "series_id",
            "quarter", "balance", "unit",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row["currency_value"] = 1000000
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_removes_negative_fv(self):
        """N-PORT rows with negative fair_value (borrowings) are filtered."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "currency_value": -50000000,
             "issuer_name": "Senior Secured Notes"},
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "currency_value": 1000000,
             "issuer_name": "Good Loan Corp"},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1
        assert "Good Loan" in result.iloc[0]["issuer_name"]

    def test_filters_null_fv(self):
        """N-PORT rows with NULL fair_value are filtered (C101)."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "currency_value": "",
             "issuer_name": "Null FV Corp"},
        ])
        result = _prepare_nport(df)
        assert len(result) == 0

    def test_keeps_zero_fv(self):
        """Zero fair_value positions are kept."""
        df = self._make_nport_df([
            {"fair_value_level": "3", "cik": "100", "asset_cat": "LON",
             "issuer_type": "CORP", "currency_value": 0,
             "issuer_name": "Zero FV Corp"},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Subsidiary flag (is_subsidiary) in _prepare_bdc
# ---------------------------------------------------------------------------

class TestSubsidiaryFlag:
    """Tests for is_subsidiary detection in _prepare_bdc."""

    def _make_bdc_row(self, **overrides):
        base = {
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Acme Corp - First Lien",
            "fair_value": 1000000.0, "cost": 990000.0,
            "principal_amount": 1000000.0, "interest_rate": 8.5,
            "basis_spread": 3.5, "reference_rate_type": "SOFR",
            "maturity_date": "2028-01-15", "pct_of_net_assets": 0.05,
            "pik_rate": None, "shares_held": None,
            "unrealized_gain_loss": 10000.0, "dimensions_raw": "axis=value",
            "investment_type": "", "industry": "", "affiliation": "",
            "period": "2023-03-31",
        }
        base.update(overrides)
        return base

    def test_subsidiary_detected_nonconsolidated(self):
        """Rows with nonconsolidatedsubsidiaryaxis are flagged is_subsidiary=1."""
        rows = [self._make_bdc_row(
            dimensions_raw="nonconsolidatedsubsidiaryaxis=JVEntity",
        )]
        df = pd.DataFrame(rows)
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert int(result.iloc[0]["is_subsidiary"]) == 1

    def test_subsidiary_detected_subsidiary_keyword(self):
        """Rows with 'subsidiary' in dimensions are flagged."""
        rows = [self._make_bdc_row(
            dimensions_raw="consolidatedsubsidiaryaxis=SubCo",
        )]
        df = pd.DataFrame(rows)
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert int(result.iloc[0]["is_subsidiary"]) == 1

    def test_non_subsidiary_not_flagged(self):
        """Normal rows without subsidiary dimensions are is_subsidiary=0."""
        rows = [self._make_bdc_row(
            dimensions_raw="investmentIdentifierAxis=AcmeCorp",
        )]
        df = pd.DataFrame(rows)
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert int(result.iloc[0]["is_subsidiary"]) == 0

    def test_null_dimensions_not_flagged(self):
        """Rows with NULL/empty dimensions_raw are is_subsidiary=0."""
        rows = [self._make_bdc_row(dimensions_raw="")]
        df = pd.DataFrame(rows)
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert int(result.iloc[0]["is_subsidiary"]) == 0

    def test_nport_always_zero(self):
        """N-PORT rows always have is_subsidiary=0."""
        nport_rows = [{
            "accession_number": "0002-45", "holding_id": "H001",
            "issuer_name": "Private Borrower LLC",
            "issuer_lei": "", "issuer_title": "Senior Secured Loan",
            "issuer_cusip": "ABC123", "currency_value": 2000000.0,
            "percentage": 0.03, "asset_cat": "LON", "issuer_type": "CORP",
            "investment_country": "US", "is_restricted_security": "Y",
            "fair_value_level": 3, "maturity_date": "2027-06-15",
            "coupon_type": "Floating", "annualized_rate": 9.0,
            "identifier_isin": "", "identifier_ticker": "",
            "payoff_profile": "Long", "cik": "456",
            "registrant_name": "Test Fund",
            "filing_date": "2023-07-15", "report_date": "2023-06-30",
            "series_name": "Test Series", "series_id": "S001",
            "quarter": "2023q2", "balance": 2000000, "unit": "PA",
            "other_unit_desc": "", "exchange_rate": None,
            "other_asset": "", "other_issuer": "", "sub_type": "",
            "derivative_cat": "", "is_default": "N",
            "other_identifier": "", "currency_code": "USD",
            "liquidity_classification": "",
            "are_any_interest_payment": "",
            "is_any_portion_interest_paid": "",
        }]
        result = _prepare_nport(pd.DataFrame(nport_rows))
        assert len(result) == 1
        assert int(result.iloc[0]["is_subsidiary"]) == 0


# ---------------------------------------------------------------------------
# Within-filing subsidiary dedup in build_unified_holdings
# ---------------------------------------------------------------------------

class TestSubsidiaryDedup:
    """Tests for within-filing subsidiary dedup in build_unified_holdings."""

    def _make_bdc_df(self, rows):
        base_cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation", "period",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in base_cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_dedup_removes_duplicate_subsidiary(self, tmp_path):
        """When same position exists under parent AND subsidiary, remove subsidiary."""
        bdc_df = self._make_bdc_df([
            # Parent row
            {"cik": "100", "entity_name": "Test BDC",
             "accession_number": "0001-23", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - First Lien",
             "fair_value": 1000000.0, "cost": 990000.0,
             "principal_amount": 1000000.0, "interest_rate": 8.5,
             "basis_spread": 3.5, "dimensions_raw": "investmentAxis=value",
             "period": "2023-03-31"},
            # Subsidiary duplicate of same position
            {"cik": "100", "entity_name": "Test BDC",
             "accession_number": "0001-23", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - First Lien",
             "fair_value": 1000000.0, "cost": 990000.0,
             "principal_amount": 1000000.0, "interest_rate": 8.5,
             "basis_spread": 3.5,
             "dimensions_raw": "nonconsolidatedsubsidiaryaxis=JV1",
             "period": "2023-03-31"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=bdc_df, nport_df=pd.DataFrame())
        # Only 1 row: the parent. The subsidiary duplicate is removed.
        acme = result[result["issuer_name"] == "Acme Corp"]
        assert len(acme) == 1
        assert int(acme.iloc[0]["is_subsidiary"]) == 0

    def test_preserves_subsidiary_only_position(self, tmp_path):
        """Subsidiary-only positions (no matching parent) are preserved."""
        bdc_df = self._make_bdc_df([
            # Parent row for a different position
            {"cik": "100", "entity_name": "Test BDC",
             "accession_number": "0001-23", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Alpha Corp - Term Loan",
             "fair_value": 500000.0, "cost": 490000.0,
             "principal_amount": 500000.0, "interest_rate": 7.0,
             "basis_spread": 2.0, "dimensions_raw": "investmentAxis=value",
             "period": "2023-03-31"},
            # Subsidiary-only position (no parent match)
            {"cik": "100", "entity_name": "Test BDC",
             "accession_number": "0001-23", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "JV-Only Holdings - Equity",
             "fair_value": 200000.0, "cost": 180000.0,
             "principal_amount": "", "interest_rate": "",
             "basis_spread": "",
             "dimensions_raw": "nonconsolidatedsubsidiaryaxis=JV1",
             "period": "2023-03-31"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=bdc_df, nport_df=pd.DataFrame())
        # Both rows preserved (different issuer_name)
        assert len(result) == 2
        jv_only = result[result["issuer_name"].str.contains("JV-Only")]
        assert len(jv_only) == 1
        assert int(jv_only.iloc[0]["is_subsidiary"]) == 1

    def test_no_subsidiary_passthrough(self, tmp_path):
        """When no subsidiary rows exist, all rows pass through unchanged."""
        bdc_df = self._make_bdc_df([
            {"cik": "100", "entity_name": "Test BDC",
             "accession_number": "0001-23", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - First Lien",
             "fair_value": 1000000.0, "cost": 990000.0,
             "principal_amount": 1000000.0, "interest_rate": 8.5,
             "basis_spread": 3.5, "dimensions_raw": "investmentAxis=value",
             "period": "2023-03-31"},
            {"cik": "100", "entity_name": "Test BDC",
             "accession_number": "0001-23", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Beta Inc - Second Lien",
             "fair_value": 800000.0, "cost": 790000.0,
             "principal_amount": 800000.0, "interest_rate": 10.0,
             "basis_spread": 5.0, "dimensions_raw": "investmentAxis=value2",
             "period": "2023-03-31"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=bdc_df, nport_df=pd.DataFrame())
        assert len(result) == 2
        assert all(result["is_subsidiary"].astype(int) == 0)


# ---------------------------------------------------------------------------
# Affiliation prefix stripping tests
# ---------------------------------------------------------------------------


class TestAffiliationPrefixStrip:
    """Tests for affiliation prefix/suffix stripping in _prepare_bdc()."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_strip_prefix(self):
        """Affiliation prefix is stripped -> issuer_name is the real company."""
        df = self._make_bdc_df([{
            "cik": "100", "investment_identifier":
                "Non-Controlled/Non-Affiliated Investments - Acme Corp - Term Loan",
            "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_strip_suffix(self):
        """Affiliation suffix is stripped -> issuer_name is correct."""
        df = self._make_bdc_df([{
            "cik": "100", "investment_identifier":
                "Acme Corp - Term Loan - Non-Controlled/Non-Affiliated",
            "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_no_strip_normal(self):
        """Normal identifier without affiliation prefix is unchanged."""
        df = self._make_bdc_df([{
            "cik": "100", "investment_identifier": "Acme Corp - Term Loan",
            "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_strip_controlled_prefix(self):
        """'Controlled Investments - ...' prefix is stripped."""
        df = self._make_bdc_df([{
            "cik": "100", "investment_identifier":
                "Controlled Investments - Beta LLC - Senior Secured",
            "fair_value": 500000,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Beta LLC"

    def test_strip_affiliate_prefix(self):
        """'Affiliate Investments - ...' prefix is stripped."""
        df = self._make_bdc_df([{
            "cik": "100", "investment_identifier":
                "Affiliate Investments - Gamma Inc - Revolver",
            "fair_value": 300000,
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Gamma Inc"


# ---------------------------------------------------------------------------
# Affiliation dedup tests
# ---------------------------------------------------------------------------


class TestAffiliationDedup:
    """Tests for affiliation-axis dedup in _prepare_bdc()."""

    def _make_bdc_df(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "pct_of_net_assets", "pik_rate", "shares_held",
            "unrealized_gain_loss", "dimensions_raw",
            "investment_type", "industry", "affiliation",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_dedup_same_issuer_fv(self):
        """Two rows, same issuer + FV, different _raw_id lengths -> 1 row kept."""
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - Term Loan",
             "fair_value": 1000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier":
                 "Non-Controlled/Non-Affiliated Investments - Acme Corp - Term Loan",
             "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        # The shorter _raw_id (after prefix strip) should be preferred
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_keep_different_fv(self):
        """Two rows, same issuer but different FV -> both kept."""
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - First Lien Term Loan",
             "fair_value": 1000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - Second Lien Term Loan",
             "fair_value": 500000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2

    def test_keep_different_issuer(self):
        """Two rows, different issuer same FV -> both kept."""
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - Term Loan",
             "fair_value": 1000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Beta Inc - Term Loan",
             "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Expanded bad issuer names tests
# ---------------------------------------------------------------------------


class TestBadIssuerNamesExpanded:
    """Tests for the expanded _BAD_ISSUER_NAMES_EXACT set."""

    def test_saratoga_bare_tag(self):
        """'Non-control/Non-affiliate investments' is filtered as bad issuer."""
        assert _is_bad_issuer_name("Non-control/Non-affiliate investments")

    def test_control_investments(self):
        """'Control investments' is filtered as bad issuer."""
        assert _is_bad_issuer_name("Control investments")

    def test_non_control_investments(self):
        """'Non-control investments' is filtered as bad issuer."""
        assert _is_bad_issuer_name("Non-control investments")

    def test_affiliate_investments(self):
        """'Affiliate investments' is filtered as bad issuer."""
        assert _is_bad_issuer_name("Affiliate investments")

    def test_non_affiliate_investments(self):
        """'Non-affiliate investments' is filtered as bad issuer."""
        assert _is_bad_issuer_name("Non-affiliate investments")


# ---------------------------------------------------------------------------
# pct_of_net_assets correction tests
# ---------------------------------------------------------------------------


class TestCorrectPctOfNetAssets:
    """Tests for _correct_pct_of_net_assets() multi-entity BDC correction."""

    def _make_holdings_df(self, rows):
        """Build a minimal unified holdings DataFrame."""
        data = []
        for row in rows:
            full_row = {c: "" for c in UNIFIED_COLUMNS}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_high_pct_corrected(self, tmp_path):
        """CIK with pct_sum=300% + net_assets available -> pct recalculated."""
        # Create a BDC with 3 positions, each showing 100% of sub-entity net assets
        holdings = self._make_holdings_df([
            {"source": "bdc", "cik": "0000000100", "report_date": "2023-03-31",
             "issuer_name": "Acme Corp", "fair_value": 1000000,
             "pct_of_net_assets": 100.0},
            {"source": "bdc", "cik": "0000000100", "report_date": "2023-03-31",
             "issuer_name": "Beta Inc", "fair_value": 2000000,
             "pct_of_net_assets": 100.0},
            {"source": "bdc", "cik": "0000000100", "report_date": "2023-03-31",
             "issuer_name": "Gamma LLC", "fair_value": 500000,
             "pct_of_net_assets": 100.0},
        ])

        # Create a fund_financials CSV with net_assets = 5,000,000
        ff_path = tmp_path / "fund_financials.csv"
        ff_df = pd.DataFrame([{
            "cik": "100", "report_date": "2023-03-31",
            "net_assets": "5000000",
        }])
        ff_df.to_csv(ff_path, index=False)

        with patch("pipeline.unified_holdings.FUND_FINANCIALS_FILE", ff_path):
            result = _correct_pct_of_net_assets(holdings)

        assert len(result) == 3
        # pct should be recalculated: fair_value / 5M * 100
        acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert abs(float(acme["pct_of_net_assets"]) - 20.0) < 0.01
        beta = result[result["issuer_name"] == "Beta Inc"].iloc[0]
        assert abs(float(beta["pct_of_net_assets"]) - 40.0) < 0.01
        gamma = result[result["issuer_name"] == "Gamma LLC"].iloc[0]
        assert abs(float(gamma["pct_of_net_assets"]) - 10.0) < 0.01

    def test_normal_pct_unchanged(self, tmp_path):
        """CIK with pct_sum=120% -> pct unchanged (below 200% threshold)."""
        holdings = self._make_holdings_df([
            {"source": "bdc", "cik": "0000000200", "report_date": "2023-03-31",
             "issuer_name": "Acme Corp", "fair_value": 600000,
             "pct_of_net_assets": 60.0},
            {"source": "bdc", "cik": "0000000200", "report_date": "2023-03-31",
             "issuer_name": "Beta Inc", "fair_value": 600000,
             "pct_of_net_assets": 60.0},
        ])

        ff_path = tmp_path / "fund_financials.csv"
        ff_df = pd.DataFrame([{
            "cik": "200", "report_date": "2023-03-31",
            "net_assets": "1000000",
        }])
        ff_df.to_csv(ff_path, index=False)

        with patch("pipeline.unified_holdings.FUND_FINANCIALS_FILE", ff_path):
            result = _correct_pct_of_net_assets(holdings)

        # pct should be unchanged (sum=120% < 200% threshold)
        acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert abs(float(acme["pct_of_net_assets"]) - 60.0) < 0.01

    def test_no_fund_financials(self, tmp_path):
        """No fund_financials file -> pct unchanged."""
        holdings = self._make_holdings_df([
            {"source": "bdc", "cik": "0000000300", "report_date": "2023-03-31",
             "issuer_name": "Acme Corp", "fair_value": 1000000,
             "pct_of_net_assets": 150.0},
            {"source": "bdc", "cik": "0000000300", "report_date": "2023-03-31",
             "issuer_name": "Beta Inc", "fair_value": 1000000,
             "pct_of_net_assets": 150.0},
        ])

        missing_path = tmp_path / "nonexistent_fund_financials.csv"
        with patch("pipeline.unified_holdings.FUND_FINANCIALS_FILE", missing_path):
            result = _correct_pct_of_net_assets(holdings)

        # Unchanged - no fund_financials file exists
        acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert abs(float(acme["pct_of_net_assets"]) - 150.0) < 0.01

    def test_nport_rows_unchanged(self, tmp_path):
        """N-PORT rows are never corrected, even in high-pct CIK-quarters."""
        holdings = self._make_holdings_df([
            {"source": "nport", "cik": "0000000400", "report_date": "2023-03-31",
             "issuer_name": "Acme Corp", "fair_value": 1000000,
             "pct_of_net_assets": 250.0},
        ])

        ff_path = tmp_path / "fund_financials.csv"
        ff_df = pd.DataFrame([{
            "cik": "400", "report_date": "2023-03-31",
            "net_assets": "1000000",
        }])
        ff_df.to_csv(ff_path, index=False)

        with patch("pipeline.unified_holdings.FUND_FINANCIALS_FILE", ff_path):
            result = _correct_pct_of_net_assets(holdings)

        # N-PORT rows should be unchanged regardless
        acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert abs(float(acme["pct_of_net_assets"]) - 250.0) < 0.01

    def test_bad_net_assets_skipped(self, tmp_path):
        """CIK with pct_sum=334% but bad net_assets ($1M vs $335M FV) -> skipped."""
        # Simulates CIK 0002012139: 30 positions totalling ~$335M, pct_sum=334%
        # fund_financials has net_assets=$1M (garbage), which would make pct_sum
        # 33,500% -- worse than 334%.  Guard should skip the correction.
        holdings = self._make_holdings_df([
            {"source": "bdc", "cik": "0002012139", "report_date": "2025-06-30",
             "issuer_name": "Alpha Corp", "fair_value": 200000000,
             "pct_of_net_assets": 200.0},
            {"source": "bdc", "cik": "0002012139", "report_date": "2025-06-30",
             "issuer_name": "Beta Inc", "fair_value": 100000000,
             "pct_of_net_assets": 100.0},
            {"source": "bdc", "cik": "0002012139", "report_date": "2025-06-30",
             "issuer_name": "Gamma LLC", "fair_value": 35000000,
             "pct_of_net_assets": 34.0},
        ])

        ff_path = tmp_path / "fund_financials.csv"
        ff_df = pd.DataFrame([{
            "cik": "2012139", "report_date": "2025-06-30",
            "net_assets": "1004000",  # Bad value: ~750x too low
        }])
        ff_df.to_csv(ff_path, index=False)

        with patch("pipeline.unified_holdings.FUND_FINANCIALS_FILE", ff_path):
            result = _correct_pct_of_net_assets(holdings)

        # Original pct values should be preserved (correction skipped)
        alpha = result[result["issuer_name"] == "Alpha Corp"].iloc[0]
        assert abs(float(alpha["pct_of_net_assets"]) - 200.0) < 0.01
        beta = result[result["issuer_name"] == "Beta Inc"].iloc[0]
        assert abs(float(beta["pct_of_net_assets"]) - 100.0) < 0.01
        gamma = result[result["issuer_name"] == "Gamma LLC"].iloc[0]
        assert abs(float(gamma["pct_of_net_assets"]) - 34.0) < 0.01

    def test_good_net_assets_applied(self, tmp_path):
        """CIK with pct_sum=400% and good net_assets -> correction applied."""
        holdings = self._make_holdings_df([
            {"source": "bdc", "cik": "0000000500", "report_date": "2023-06-30",
             "issuer_name": "Acme Corp", "fair_value": 2000000,
             "pct_of_net_assets": 200.0},
            {"source": "bdc", "cik": "0000000500", "report_date": "2023-06-30",
             "issuer_name": "Beta Inc", "fair_value": 2000000,
             "pct_of_net_assets": 200.0},
        ])

        ff_path = tmp_path / "fund_financials.csv"
        ff_df = pd.DataFrame([{
            "cik": "500", "report_date": "2023-06-30",
            "net_assets": "10000000",  # Good: recalculated pct_sum = 40% < 400%
        }])
        ff_df.to_csv(ff_path, index=False)

        with patch("pipeline.unified_holdings.FUND_FINANCIALS_FILE", ff_path):
            result = _correct_pct_of_net_assets(holdings)

        # pct should be recalculated: 2M / 10M * 100 = 20%
        acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert abs(float(acme["pct_of_net_assets"]) - 20.0) < 0.01
        beta = result[result["issuer_name"] == "Beta Inc"].iloc[0]
        assert abs(float(beta["pct_of_net_assets"]) - 20.0) < 0.01

    def test_below_threshold_no_correction(self, tmp_path):
        """CIK with pct_sum=150% -> below 200% threshold, no correction."""
        holdings = self._make_holdings_df([
            {"source": "bdc", "cik": "0000000600", "report_date": "2023-06-30",
             "issuer_name": "Acme Corp", "fair_value": 800000,
             "pct_of_net_assets": 80.0},
            {"source": "bdc", "cik": "0000000600", "report_date": "2023-06-30",
             "issuer_name": "Beta Inc", "fair_value": 700000,
             "pct_of_net_assets": 70.0},
        ])

        ff_path = tmp_path / "fund_financials.csv"
        ff_df = pd.DataFrame([{
            "cik": "600", "report_date": "2023-06-30",
            "net_assets": "1000000",
        }])
        ff_df.to_csv(ff_path, index=False)

        with patch("pipeline.unified_holdings.FUND_FINANCIALS_FILE", ff_path):
            result = _correct_pct_of_net_assets(holdings)

        # pct unchanged (sum=150% < 200% threshold)
        acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert abs(float(acme["pct_of_net_assets"]) - 80.0) < 0.01


# ---------------------------------------------------------------------------
# _apply_row_corrections
# ---------------------------------------------------------------------------

class TestApplyRowCorrections:
    """Tests for row_corrections.csv overlay."""

    def _make_holdings_df(self, rows):
        data = []
        for row in rows:
            full_row = {c: "" for c in UNIFIED_COLUMNS}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def _write_corrections(self, tmp_path, rows):
        import csv
        path = tmp_path / "row_corrections.csv"
        cols = [
            "cik", "report_date", "accession_number",
            "bdc_investment_identifier", "field", "value",
            "reason", "source_evidence", "author", "date_added",
        ]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                full = {c: "" for c in cols}
                full.update(r)
                w.writerows([full])
        return path

    def test_correction_applied(self, tmp_path):
        """Matching correction row updates the target field."""
        df = self._make_holdings_df([{
            "source": "bdc",
            "cik": "0000001234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "fair_value": "",
            "issuer_name": "Acme Corp",
        }])
        corr_path = self._write_corrections(tmp_path, [{
            "cik": "1234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "field": "fair_value",
            "value": "5000000",
            "reason": "test correction",
            "source_evidence": "test",
            "author": "test",
            "date_added": "2026-01-01",
        }])

        result = _apply_row_corrections(df, corrections_path=corr_path)
        assert result.iloc[0]["fair_value"] == "5000000"

    def test_non_matching_correction_skipped(self, tmp_path):
        """Correction with no matching row is skipped (logged as warning)."""
        df = self._make_holdings_df([{
            "source": "bdc",
            "cik": "0000001234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "fair_value": "1000000",
            "issuer_name": "Acme Corp",
        }])
        corr_path = self._write_corrections(tmp_path, [{
            "cik": "9999",
            "report_date": "2024-06-30",
            "accession_number": "0000000099-24-000001",
            "bdc_investment_identifier": "No Such Position",
            "field": "fair_value",
            "value": "5000000",
            "reason": "unmatched correction",
            "source_evidence": "test",
            "author": "test",
            "date_added": "2026-01-01",
        }])

        result = _apply_row_corrections(df, corrections_path=corr_path)
        # Original value unchanged
        assert result.iloc[0]["fair_value"] == "1000000"

    def test_empty_corrections_file_noop(self, tmp_path):
        """Empty corrections CSV is a no-op."""
        df = self._make_holdings_df([{
            "source": "bdc",
            "cik": "0000001234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "fair_value": "1000000",
        }])
        corr_path = self._write_corrections(tmp_path, [])

        result = _apply_row_corrections(df, corrections_path=corr_path)
        assert result.iloc[0]["fair_value"] == "1000000"

    def test_missing_corrections_file_noop(self, tmp_path):
        """Non-existent corrections file is a no-op."""
        df = self._make_holdings_df([{
            "source": "bdc",
            "cik": "0000001234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "fair_value": "1000000",
        }])
        missing = tmp_path / "nonexistent.csv"
        result = _apply_row_corrections(df, corrections_path=missing)
        assert result.iloc[0]["fair_value"] == "1000000"

    def test_multiple_fields_same_row(self, tmp_path):
        """Two corrections on the same row update both fields."""
        df = self._make_holdings_df([{
            "source": "bdc",
            "cik": "0000001234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "fair_value": "",
            "principal_amount": "",
            "issuer_name": "Acme Corp",
        }])
        corr_path = self._write_corrections(tmp_path, [
            {
                "cik": "1234",
                "report_date": "2024-06-30",
                "accession_number": "0000000001-24-000001",
                "bdc_investment_identifier": "Acme Corp - Term Loan",
                "field": "fair_value",
                "value": "5000000",
                "reason": "FV correction",
                "source_evidence": "test",
                "author": "test",
                "date_added": "2026-01-01",
            },
            {
                "cik": "1234",
                "report_date": "2024-06-30",
                "accession_number": "0000000001-24-000001",
                "bdc_investment_identifier": "Acme Corp - Term Loan",
                "field": "principal_amount",
                "value": "5100000",
                "reason": "PA correction",
                "source_evidence": "test",
                "author": "test",
                "date_added": "2026-01-01",
            },
        ])

        result = _apply_row_corrections(df, corrections_path=corr_path)
        assert result.iloc[0]["fair_value"] == "5000000"
        assert result.iloc[0]["principal_amount"] == "5100000"

    def test_invalid_field_skipped(self, tmp_path):
        """Correction for a non-correctable field is skipped."""
        df = self._make_holdings_df([{
            "source": "bdc",
            "cik": "0000001234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "fair_value": "1000000",
            "issuer_name": "Acme Corp",
        }])
        corr_path = self._write_corrections(tmp_path, [{
            "cik": "1234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "field": "cik",
            "value": "9999999999",
            "reason": "should not be allowed",
            "source_evidence": "test",
            "author": "test",
            "date_added": "2026-01-01",
        }])

        result = _apply_row_corrections(df, corrections_path=corr_path)
        # CIK unchanged -- field not in _CORRECTABLE_FIELDS
        assert result.iloc[0]["cik"] == "0000001234"

    def test_missing_required_columns_skipped(self, tmp_path):
        """Corrections file missing required columns is skipped entirely."""
        # Write a malformed CSV missing 'reason' and 'source_evidence'
        path = tmp_path / "bad_corrections.csv"
        pd.DataFrame([{
            "cik": "1234",
            "report_date": "2024-06-30",
            "field": "fair_value",
            "value": "9999",
        }]).to_csv(path, index=False)

        df = self._make_holdings_df([{
            "source": "bdc",
            "cik": "0000001234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "fair_value": "1000000",
        }])

        result = _apply_row_corrections(df, corrections_path=path)
        # No correction applied -- schema validation failed
        assert result.iloc[0]["fair_value"] == "1000000"

    def test_cik_zero_padding(self, tmp_path):
        """CIK with and without zero-padding matches correctly."""
        df = self._make_holdings_df([{
            "source": "bdc",
            "cik": "0000845385",
            "report_date": "2025-06-30",
            "accession_number": "0001213900-25-075759",
            "bdc_investment_identifier": "Rockfish - Revolving Loan",
            "fair_value": "",
        }])
        corr_path = self._write_corrections(tmp_path, [{
            "cik": "845385",
            "report_date": "2025-06-30",
            "accession_number": "0001213900-25-075759",
            "bdc_investment_identifier": "Rockfish - Revolving Loan",
            "field": "fair_value",
            "value": "2251000",
            "reason": "CIK padding test",
            "source_evidence": "test",
            "author": "test",
            "date_added": "2026-01-01",
        }])

        result = _apply_row_corrections(df, corrections_path=corr_path)
        assert result.iloc[0]["fair_value"] == "2251000"

    def test_other_rows_unchanged(self, tmp_path):
        """Correction only affects the matched row; others are untouched."""
        df = self._make_holdings_df([
            {
                "source": "bdc",
                "cik": "0000001234",
                "report_date": "2024-06-30",
                "accession_number": "0000000001-24-000001",
                "bdc_investment_identifier": "Acme Corp - Term Loan",
                "fair_value": "",
                "issuer_name": "Acme Corp",
            },
            {
                "source": "bdc",
                "cik": "0000001234",
                "report_date": "2024-06-30",
                "accession_number": "0000000001-24-000001",
                "bdc_investment_identifier": "Beta Inc - Revolver",
                "fair_value": "2000000",
                "issuer_name": "Beta Inc",
            },
        ])
        corr_path = self._write_corrections(tmp_path, [{
            "cik": "1234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "field": "fair_value",
            "value": "5000000",
            "reason": "test",
            "source_evidence": "test",
            "author": "test",
            "date_added": "2026-01-01",
        }])

        result = _apply_row_corrections(df, corrections_path=corr_path)
        assert result.iloc[0]["fair_value"] == "5000000"
        assert result.iloc[1]["fair_value"] == "2000000"

    def test_correctable_fields_includes_key_fields(self):
        """Spot-check that _CORRECTABLE_FIELDS includes the expected set."""
        for f in ("fair_value", "cost", "principal_amount",
                  "interest_rate", "basis_spread", "index_classification"):
            assert f in _CORRECTABLE_FIELDS

    def test_no_corr_key_column_leaked(self, tmp_path):
        """The internal _corr_key column is not present in the output."""
        df = self._make_holdings_df([{
            "source": "bdc",
            "cik": "0000001234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "fair_value": "",
        }])
        corr_path = self._write_corrections(tmp_path, [{
            "cik": "1234",
            "report_date": "2024-06-30",
            "accession_number": "0000000001-24-000001",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
            "field": "fair_value",
            "value": "5000000",
            "reason": "test",
            "source_evidence": "test",
            "author": "test",
            "date_added": "2026-01-01",
        }])

        result = _apply_row_corrections(df, corrections_path=corr_path)
        assert "_corr_key" not in result.columns
