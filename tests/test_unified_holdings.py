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

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from pipeline.bdc_identifier import (
    _AFFILIATION_TAGS,
    _is_bad_issuer_name,
    _is_bdc_aggregate_row,
    _parse_bdc_identifier,
)
from pipeline.classification import (
    _INDUSTRY_LABELS,
    _classify_bdc_asset,
    _classify_bdc_issuer,
    _classify_index,
    _classify_nport_asset,
    _classify_nport_issuer,
    _infer_coupon_type,
    _is_named_coinvest,
    _normalize_rate,
    _sql_classify_asset_class,
    _sql_classify_exposure_type,
    _sql_classify_index,
)
from pipeline.staging_bdc import (
    _load_aggregate_header_flags,
    _prepare_bdc,
    _reclassify_named_fund_positions,
)
from pipeline.bdc_xbrl_html_bridge import BRIDGE_TABLE_COLUMNS
from pipeline.staging_nport import _prepare_nport
from pipeline.unified_holdings import _apply_wrapper_position_keys
from pipeline.unified_holdings import (
    _apply_universe_gate,
    _apply_row_corrections,
    _apply_unclassified_cache,
    _CORRECTABLE_FIELDS,
    _correct_pct_of_net_assets,
    _enforce_schema,
    _restore_deterministic_classification_rules,
    _stabilize_classification,
    build_unified_holdings,
    UNIFIED_COLUMNS,
)

SLOW_INTEGRATION_MARKS = [pytest.mark.slow, pytest.mark.integration]
SLOW_STAGING_SQL_MARKS = [pytest.mark.slow, pytest.mark.staging_sql]


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

    def test_flexible_pipe_spacing(self):
        issuer, instrument = _parse_bdc_identifier(
            "Acme Corp|Software|First Lien Term Loan"
        )
        assert issuer == "Acme Corp"
        assert instrument == "First Lien Term Loan"

    def test_slr_equipment_financing_seg2_leaf(self):
        issuer, instrument = _parse_bdc_identifier(
            "Equipment Financing - 24.1% | Air Methods Corporation |Airlines| "
            "First Lien Term Loan | SOFR + 6.00% | 12/31/2028"
        )
        assert issuer == "Air Methods Corporation"
        assert "Equipment Financing - 24.1%" in instrument
        assert "Airlines" in instrument

    def test_slr_equipment_financing_industry_not_issuer(self):
        issuer, instrument = _parse_bdc_identifier(
            "Equipment Financing - 24.1% | Diversified Consumer Services| "
            "Total Diversified Consumer Services"
        )
        assert issuer == "Total Diversified Consumer Services"
        assert "Diversified Consumer Services" in instrument


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

    def test_affiliation_bucket_with_economic_detail_is_subtotal(self):
        """Industry-prefixed category subtotals ending with affiliation text
        (e.g. Star Mountain, Saratoga) should be filtered as aggregates."""
        assert _is_bdc_aggregate_row(
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

    def test_total_equipment_financing_flexible_pipe_spacing(self):
        assert _is_bdc_aggregate_row(
            "Equipment Financing - 24.1% |Total Equipment Financing"
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

    # --- Non-control dimension-path handling (2026-05-04, updated P0-A) ---
    def test_long_noncontrol_dimension_path_with_entity_kept_pre_strip(self):
        """Long dimension-path identifier with affiliation prefix BUT entity
        signals ('Holding Company' -> 'holdings') and leaf detail ('Delayed
        Draw' + 'SOFR') is NOT filtered because the entity/leaf guards
        protect it. In the pipeline, _INVESTMENTS_HIERARCHY_RE strips the
        prefix first anyway."""
        long_id = (
            "Non-Controlled/Non-Affiliated Investments Senior Secured First Lien Loans "
            "Industry Commercial Services & Supplies Company Advanced Web Technologies "
            "Holding Company Delayed Draw SOFR Spread 5.75"
        )
        assert len(long_id) >= 150  # sanity check
        # Entity signal 'holdings' and leaf detail protect this from aggregate filter
        assert not _is_bdc_aggregate_row(long_id)

    def test_short_noncontrol_without_entity_no_leaf_filtered_pre_strip(self):
        """Affiliation prefix without entity signals or leaf detail IS filtered
        pre-strip (validates the Python mirror catches category-only identifiers)."""
        short_id = (
            "Non-Controlled/Non-Affiliated Investments Senior Secured First Lien Loans"
        )
        assert _is_bdc_aggregate_row(short_id)

    def test_investments_hierarchy_stripped_identifier_kept(self):
        """After _INVESTMENTS_HIERARCHY_RE stripping, the remaining
        identifier (company name + economic detail) should NOT be filtered."""
        import re
        from pipeline.bdc_identifier import _INVESTMENTS_HIERARCHY_RE
        # Fidelity-style: "Investments -- non-controlled/ non-affiliate Equity ..."
        fidelity_id = (
            "Investments -- non-controlled/ non-affiliate Equity "
            "Software BPCP Crafts Intermediate LLC Term Loan SOFR 5.75"
        )
        stripped = re.sub(_INVESTMENTS_HIERARCHY_RE, "", fidelity_id)
        assert stripped != fidelity_id, "Regex should strip the hierarchy prefix"
        assert not _is_bdc_aggregate_row(stripped)

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

    # --- P0-A: Aggregate filter hardening ---

    def test_fidelity_central_format_not_filtered_after_stripping(self):
        """Fidelity Central dimension-path identifiers should NOT be filtered
        after hierarchy stripping removes 'Investments -- non-controlled/...' prefix.
        Post-strip: 'Software BPCP Crafts Intermediate LLC'."""
        # After _INVESTMENTS_HIERARCHY_RE strips, only company + industry remain
        assert not _is_bdc_aggregate_row("Software BPCP Crafts Intermediate LLC")

    def test_fidelity_private_credit_format_not_filtered_after_stripping(self):
        """Fidelity Private Credit dimension-path after stripping should NOT be filtered.
        Post-strip: 'Healthcare Acme Health Holdings LLC Term Loan'."""
        assert not _is_bdc_aggregate_row(
            "Healthcare Acme Health Holdings LLC Term Loan"
        )

    def test_msd_format_not_filtered_after_stripping(self):
        """MSD Partners dimension-path after stripping should NOT be filtered.
        Post-strip: 'Consumer Services Acme Corp. Senior Secured First Lien'."""
        assert not _is_bdc_aggregate_row(
            "Consumer Services Acme Corp. Senior Secured First Lien"
        )

    def test_sixth_street_rate_suffix_not_filtered(self):
        """Sixth Street identifiers ending with 'Interest rate 10.5%'
        should NOT be filtered -- the pct suffix guard excludes financial-term context."""
        assert not _is_bdc_aggregate_row(
            "Acme Widgets Senior Secured First Lien Term Loan Interest rate 10.5%"
        )

    def test_sixth_street_sofr_rate_suffix_not_filtered(self):
        """Identifiers ending with 'SOFR + 3.5%' should NOT be filtered."""
        assert not _is_bdc_aggregate_row(
            "Acme Widgets Term Loan SOFR 8.5%"
        )

    def test_diameter_format_not_filtered_after_stripping(self):
        """Diameter Capital dimension-path after stripping should NOT be filtered.
        Post-strip: 'Technology Widgetco Holdings LLC First Lien'."""
        assert not _is_bdc_aggregate_row(
            "Technology Widgetco Holdings LLC First Lien"
        )

    def test_bare_affiliation_header_still_filtered(self):
        """Bare affiliation section headers must still be filtered (regression guard)."""
        assert _is_bdc_aggregate_row("Non-Controlled/Non-Affiliated Investments")
        assert _is_bdc_aggregate_row("Affiliate Investments")
        assert _is_bdc_aggregate_row("Controlled Investments")

    def test_star_mountain_category_subtotal_with_affiliation_suffix_filtered(self):
        """Star Mountain/Saratoga-style category subtotals ending with
        affiliation text should be filtered."""
        assert _is_bdc_aggregate_row(
            "Construction & Engineering First Lien Senior Secured "
            "Term Loan Non-Affiliate Investments"
        )
        assert _is_bdc_aggregate_row(
            "Technology Software First Lien Non-Controlled/Non-Affiliated Investments"
        )

    def test_percentage_subtotal_without_financial_context_still_filtered(self):
        """Percentage-suffix subtotals without financial context should still be filtered
        (regression guard for the pct guard change)."""
        assert _is_bdc_aggregate_row("Debt Investment 96.8%")
        assert _is_bdc_aggregate_row("United States - 1.60%")

    def test_hierarchy_stripping_preserves_company_name(self):
        """After stripping, the remaining identifier should have the company name
        and be parseable for issuer extraction. Test via Python _parse_bdc_identifier."""
        # This tests that the hierarchy regex leaves a usable identifier.
        # "Software BPCP Crafts Intermediate LLC" -> issuer = full string (no dash)
        issuer, _ = _parse_bdc_identifier("Software BPCP Crafts Intermediate LLC")
        assert "BPCP Crafts" in issuer or "LLC" in issuer


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
    pytestmark = SLOW_STAGING_SQL_MARKS

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

    def test_src_context_id_passes_through_bdc_staging(self):
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp - Term Loan", "cik": "123",
             "fair_value": 1000000, "src_context_id": "ctx_acme_tl1"},
        ])
        result = _prepare_bdc(df)
        assert "src_context_id" in result.columns
        assert list(result["src_context_id"]) == ["ctx_acme_tl1"]

    def test_src_context_id_defaults_empty_when_absent(self):
        # bdc_holdings.csv built before the migration has no src_context_id
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp - Term Loan", "cik": "123",
             "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert "src_context_id" in result.columns
        assert list(result["src_context_id"]) == [""]

    def test_returns_empty_when_wrapper_filters_all_phase_a_rows(self):
        """All-rollup wrapper CIKs return an empty staged frame, not Phase B SQL errors."""
        df = self._make_bdc_df([
            {
                "investment_identifier": "Second Lien Secured Debt",
                "cik": "0002008748",
                "entity_name": "Lord Abbett Private Credit Fund",
                "report_date": "2026-03-31",
                "fair_value": 26389000,
                "dimensions_raw": "investmentidentifieraxis=Second Lien Secured Debt",
            },
            {
                "investment_identifier": "Total Investments at Fair Value",
                "cik": "0002008748",
                "entity_name": "Lord Abbett Private Credit Fund",
                "report_date": "2026-03-31",
                "fair_value": 1413006000,
                "dimensions_raw": "investmentidentifieraxis=Total Investments at Fair Value",
            },
        ])

        result = _prepare_bdc(df)

        assert result.empty
        assert list(result.columns) == UNIFIED_COLUMNS

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

    def test_position_key_preserves_issuer_for_class_units(self):
        """Class-unit equity rows must not collapse to generic keys."""
        df = self._make_bdc_df([
            {"investment_identifier": "CATBIRD NYC, LLC, Class A Units",
             "cik": "123", "fair_value": 1396000, "shares_held": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        key = result.iloc[0]["position_key"]
        assert "catbird" in key
        assert key != "lass units"

    def test_position_key_preserves_numbered_loan_tranches(self):
        """Ares-style trailing loan numbers identify separate positions."""
        df = self._make_bdc_df([
            {"investment_identifier": "North Haven Stack Buyer, LLC, First lien senior secured loan 1",
             "cik": "0001287750", "fair_value": 1800000, "principal_amount": 1800000},
            {"investment_identifier": "North Haven Stack Buyer, LLC, First lien senior secured loan 2",
             "cik": "0001287750", "fair_value": 3500000, "principal_amount": 3500000},
        ])
        result = _prepare_bdc(df)
        keys = set(result["position_key"])
        assert len(keys) == 2
        assert any(key.endswith("loan 1") for key in keys)
        assert any(key.endswith("loan 2") for key in keys)

    def test_silver_point_wrapper_extracts_comma_hierarchy_leaf(self):
        """Silver Point early comma hierarchy rows are positions, not subtotals."""
        df = self._make_bdc_df([
            {
                "cik": "0001646614",
                "entity_name": "Silver Point Specialty Credit Fund, L.P.",
                "accession_number": "0000950170-23-042115",
                "report_date": "2023-06-30",
                "investment_identifier": (
                    "Non-Controlled/Non-Affiliated Investments, Secured Loans, "
                    "1st Lien Term Loan, Luxembourg, Mallinckrodt International "
                    "Finance S.A., Pharmaceuticals & Life Sciences, Rate L+5.25%, "
                    "0.75% Floor, Interest Rate 10.40%, Original Acquisition Date "
                    "10/13/2020, Maturity Date 9/30/2027"
                ),
                "fair_value": 7909754,
                "interest_rate": 0.104,
                "maturity_date": "2027-09-30",
            },
            {
                "cik": "0001646614",
                "entity_name": "Silver Point Specialty Credit Fund, L.P.",
                "accession_number": "0000950170-23-042115",
                "report_date": "2023-06-30",
                "investment_identifier": "Controlled Investments, Total Trust Interest",
                "fair_value": 2304179,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Mallinckrodt International Finance S.A."
        assert "1st Lien Term Loan" in row["instrument_description"]
        assert row["maturity_date"] == "2027-09-30"

    def test_tpg_twin_brook_comma_debt_leaf_extracts_instrument(self):
        """TPG comma-delimited leaf rows should split issuer from loan terms."""
        df = self._make_bdc_df([
            {
                "investment_identifier": (
                    "AFC-Dell Holding Corp, First lien senior secured revolving loan 2"
                ),
                "cik": "0001913724",
                "entity_name": "TPG Twin Brook Capital Income Fund",
                "fair_value": 1800000,
                "principal_amount": 1800000,
                "interest_rate": 0.105,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "AFC-Dell Holding Corp"
        assert row["instrument_description"] == (
            "First lien senior secured revolving loan 2"
        )
        assert row["asset_category"] == "LOAN"

    def test_tpg_twin_brook_comma_subordinated_note_extracts_instrument(self):
        """Sponsor subordinated notes use the same TPG comma staging path."""
        df = self._make_bdc_df([
            {
                "investment_identifier": (
                    "Cosmetic Solutions LLC, Sponsor subordinated note"
                ),
                "cik": "0001913724",
                "entity_name": "TPG Twin Brook Capital Income Fund",
                "fair_value": 250000,
                "principal_amount": 250000,
                "interest_rate": 0.12,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Cosmetic Solutions LLC"
        assert row["instrument_description"] == "Sponsor subordinated note"
        assert row["asset_category"] == "LOAN"

    def test_ab_private_credit_pipe_hierarchy_extracts_issuer_and_instrument(self):
        """AB pipe hierarchy rows should parse issuer after category segments."""
        df = self._make_bdc_df([
            {
                "investment_identifier": (
                    "U.S. Corporate Debt | 1st Lien/Senior Secured Debt | "
                    "Fusion Holding Corp | Software & Tech Services | Term Loan "
                    "| 11.59% (S + 6.25%; 0.75% Floor)| 09/15/2029"
                ),
                "cik": "0001634452",
                "entity_name": "AB Private Credit Investors Corp",
                "fair_value": 16600665,
                "cost": 16500000,
                "principal_amount": 16600000,
                "interest_rate": 0.1159,
                "maturity_date": "2029-09-15",
            },
            {
                "investment_identifier": (
                    "U.S. Common Stock | Stripe, Inc. | Class B Common Stock | "
                    "Software & Tech Services | 5/17/2021"
                ),
                "cik": "0001634452",
                "entity_name": "AB Private Credit Investors Corp",
                "fair_value": 171725,
                "cost": 166854,
                "shares_held": 4158,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 2
        by_issuer = {row["issuer_name"]: row for _, row in result.iterrows()}
        assert "Fusion Holding Corp" in by_issuer
        assert "Stripe, Inc." in by_issuer
        assert "Term Loan" in by_issuer["Fusion Holding Corp"]["instrument_description"]
        assert (
            by_issuer["Stripe, Inc."]["instrument_description"]
            == "Class B Common Stock | Software & Tech Services | 5/17/2021"
        )

    def test_tpg_twin_brook_pipe_leaf_still_extracts_instrument(self):
        """TPG staging must not override existing pipe-delimited parsing."""
        df = self._make_bdc_df([
            {
                "investment_identifier": (
                    "AFC-Dell Holding Corp | First lien senior secured "
                    "delayed draw term loan 1"
                ),
                "cik": "0001913724",
                "entity_name": "TPG Twin Brook Capital Income Fund",
                "fair_value": 900000,
                "principal_amount": 900000,
                "interest_rate": 0.11,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "AFC-Dell Holding Corp"
        assert row["instrument_description"] == (
            "First lien senior secured delayed draw term loan 1"
        )

    def test_tpg_twin_brook_bare_equity_holding_not_comma_split(self):
        """Bare recurring TPG equity holding rows remain standalone positions."""
        df = self._make_bdc_df([
            {
                "investment_identifier": "Twin Brook Equity Holdings, LLC",
                "cik": "0001913724",
                "entity_name": "TPG Twin Brook Capital Income Fund",
                "fair_value": 100000,
                "shares_held": 1000,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Twin Brook Equity Holdings, LLC"
        assert row["instrument_description"] == ""
        assert row["asset_category"] == "EQUITY_COMMON"

    def test_triplepoint_global_comma_equity_leaf_extracts_issuer(self):
        """TriplePoint comma-delimited equity leaves split issuer and instrument."""
        df = self._make_bdc_df([
            {
                "investment_identifier": "JOKR S.a.r.l. 1, Equity Investments",
                "cik": "0001792509",
                "entity_name": "TriplePoint Global Venture Credit, LLC",
                "fair_value": 328000,
                "cost": 375000,
                "shares_held": 5688,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "JOKR S.a.r.l. 1"
        assert row["instrument_description"] == "Equity Investments"
        assert row["asset_category"] == "EQUITY_COMMON"

    def test_triplepoint_global_pipe_equity_leaf_extracts_issuer(self):
        """TriplePoint four-segment pipe equity leaves keep issuer and stock type."""
        df = self._make_bdc_df([
            {
                "investment_identifier": (
                    "JOKR S.a.r.l. | Preferred Stock 3 | Equity Investments "
                    "|Non-Affiliated Issuer"
                ),
                "cik": "0001792509",
                "entity_name": "TriplePoint Global Venture Credit, LLC",
                "fair_value": 1443000,
                "cost": 662000,
                "shares_held": 99189,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "JOKR S.a.r.l."
        assert row["instrument_description"] == "Preferred Stock 3"
        assert row["asset_category"] == "EQUITY_PREFERRED"

    def test_html_section_bridge_fills_missing_instrument(self, monkeypatch):
        """Exact HTML-section bridge records repair XBRL rows missing instrument text."""
        import pipeline.staging_bdc as staging_bdc

        bridge_rows = pd.DataFrame(
            [
                {
                    "cik": "0000000123",
                    "accession_number": "0000000000-26-000001",
                    "report_date": "2026-03-31",
                    "raw_id_lower": "acme corp",
                    "issuer_name": "Acme Corp",
                    "instrument_description": "First Lien Debt",
                    "family": "debt",
                    "disposition": "debt_position_leaf",
                    "rule_id": "HTML_SECTION_BRIDGE_DEBT_LEAF_V1",
                    "html_sha256": "c" * 64,
                    "table_index": 1,
                    "section_row_index": 2,
                    "row_index": 3,
                    "cell_indices": "[0, 1, 2]",
                    "section_label": "First Lien Debt",
                    "permit_overwrite": False,
                }
            ],
            columns=BRIDGE_TABLE_COLUMNS,
        )
        monkeypatch.setattr(
            staging_bdc,
            "_load_html_section_bridges_from_json",
            lambda: bridge_rows,
        )
        df = self._make_bdc_df([
            {
                "investment_identifier": "Acme Corp",
                "cik": "0000000123",
                "accession_number": "0000000000-26-000001",
                "report_date": "2026-03-31",
                "fair_value": 2000000,
                "cost": 1000000,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Acme Corp"
        assert row["instrument_description"] == "First Lien Debt"
        assert row["asset_category"] == "LOAN"

    def test_msd_hierarchy_leaf_rows_without_legal_suffix_are_kept(self):
        """MSD hierarchy rows are position leaves even when issuer lacks LLC/Inc."""
        df = self._make_bdc_df([
            {
                "cik": "0001849894",
                "entity_name": "MSD Investment Corp.",
                "accession_number": "0001193125-26-124538",
                "report_date": "2025-12-31",
                "investment_identifier": (
                    "Investments Investments - non-controlled/non-affiliated "
                    "First Lien Debt Banking, Finance, Insurance & Real Estate "
                    "7Ridge Investments - Delayed Draw Term Loan Reference Rate "
                    "and Spread S + 8.00% Interest Rate Floor 1.00% Interest "
                    "Rate 11.67% Maturity Date 7/7/2028"
                ),
                "fair_value": 11123000,
                "cost": 11123000,
                "principal_amount": 11277000,
                "interest_rate": 0.1167,
            },
            {
                "cik": "0001849894",
                "entity_name": "MSD Investment Corp.",
                "accession_number": "0001193125-26-124538",
                "report_date": "2025-12-31",
                "investment_identifier": (
                    "Investments Investments - non-controlled/non-affiliated "
                    "Common Equity Services: Business S.A.F.E. Management "
                    "Equity Interest Rate 0.00% Maturity Date 11/24/2031"
                ),
                "fair_value": 3478000,
                "cost": 3478000,
                "principal_amount": 3478000,
            },
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        by_issuer = {row["issuer_name"]: row for _, row in result.iterrows()}
        assert "7Ridge Investments" in by_issuer
        assert by_issuer["7Ridge Investments"]["instrument_description"].startswith(
            "Delayed Draw Term Loan"
        )
        assert "S.A.F.E. Management" in by_issuer
        assert by_issuer["S.A.F.E. Management"]["asset_category"] == "EQUITY_COMMON"

    def test_msd_hierarchy_parser_is_cik_scoped_false_positive_guard(self):
        """The MSD hierarchy exception does not globally admit generic rows."""
        df = self._make_bdc_df([
            {
                "cik": "0000000123",
                "investment_identifier": (
                    "Investments Investments - non-controlled/non-affiliated "
                    "First Lien Debt Banking, Finance, Insurance & Real Estate "
                    "7Ridge Investments - Delayed Draw Term Loan Reference Rate "
                    "and Spread S + 8.00% Interest Rate 11.67% Maturity Date 7/7/2028"
                ),
                "fair_value": 11123000,
                "principal_amount": 11277000,
                "interest_rate": 0.1167,
            }
        ])
        result = _prepare_bdc(df)
        assert result.empty

    def test_fidelity_equity_coinvest_class_a_units_kept(self):
        """Equity co-investments with Class A/B Units/Interest survive prefix hierarchy filter."""
        df = self._make_bdc_df([
            {
                "cik": "0001920453",
                "entity_name": "Fidelity Private Credit Fund",
                "accession_number": "0000950170-25-041963",
                "report_date": "2024-12-31",
                "investment_identifier": (
                    "Investments Investments - non-controlled / non-affiliate "
                    "Equity Specialized Consumer Services Quick Roofing Topco, "
                    "LLC Class A Interest"
                ),
                "fair_value": 1359672,
            },
            {
                "cik": "0001920453",
                "entity_name": "Fidelity Private Credit Fund",
                "accession_number": "0000950170-25-041963",
                "report_date": "2024-12-31",
                "investment_identifier": (
                    "Investments Investments - non-controlled / non-affiliate "
                    "Equity Industrial Machinery & Supplies & Components "
                    "MoboTrex Ultimate Holdings, LLC Class A-2 Units"
                ),
                "fair_value": 1027063,
            },
            {
                "cik": "0001920453",
                "entity_name": "Fidelity Private Credit Fund",
                "accession_number": "0000950170-25-041963",
                "report_date": "2024-12-31",
                "investment_identifier": (
                    "Investments Investments - non-controlled / non-affiliate "
                    "Equity Health Care Services NE Ortho Holdings, LLC "
                    "Class B Membership Units"
                ),
                "fair_value": 135260,
            },
        ])
        result = _prepare_bdc(df)
        assert len(result) == 3, (
            f"Expected 3 equity co-investments, got {len(result)}"
        )

    def test_fidelity_central_hierarchy_extracts_issuer_and_instrument(self):
        """Fidelity Central uses the same hierarchy guard with its own CIK config."""
        df = self._make_bdc_df([
            {
                "cik": "0001899996",
                "entity_name": "Fidelity Private Credit Co LLC",
                "accession_number": "0000950170-25-108878",
                "report_date": "2025-06-30",
                "investment_identifier": (
                    "Investments Investments -- non-controlled/ non-affiliated "
                    "First Lien Debt Automotive Parts & Equipment Arrowhead "
                    "Holdco Company Term Loan Reference Rate and Spread SOFR + "
                    "5.25% Interest Rate 10.75% Maturity Date 8/31/2028"
                ),
                "fair_value": 20863478,
                "cost": 24883407,
                "principal_amount": 25289064,
                "interest_rate": 0.1075,
                "maturity_date": "2028-08-31",
            },
            {
                "cik": "0001899996",
                "entity_name": "Fidelity Private Credit Co LLC",
                "accession_number": "0000950170-26-050001",
                "report_date": "2026-03-31",
                "investment_identifier": (
                    "Investments -- non-controlled/ non-affiliate Equity "
                    "Aerospace & Defense Hitco Parent LLC Type Class A Units"
                ),
                "fair_value": 131104,
                "cost": 109890,
                "shares_held": 8723,
            },
            {
                "cik": "0001899996",
                "entity_name": "Fidelity Private Credit Co LLC",
                "accession_number": "0000950170-25-001234",
                "report_date": "2024-09-30",
                "investment_identifier": (
                    "Investments Investments -- non-controlled/ non-affiliatd "
                    "First Lien Debt Application Software Routeware, Inc "
                    "Delayed Draw Term Loan Maturity Date 9/18/2031"
                ),
                "fair_value": 1000,
                "cost": 1000,
                "principal_amount": 1000,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 3
        by_issuer = {row["issuer_name"]: row for _, row in result.iterrows()}
        assert "Arrowhead Holdco Company" in by_issuer
        assert "Term Loan" in by_issuer["Arrowhead Holdco Company"]["instrument_description"]
        assert "Hitco Parent LLC" in by_issuer
        assert "Class A Units" in by_issuer["Hitco Parent LLC"]["instrument_description"]
        assert "Routeware, Inc" in by_issuer
        assert "Delayed Draw Term Loan" in by_issuer["Routeware, Inc"]["instrument_description"]

    def test_prefix_parent_with_one_suffix_child_is_retained(self):
        """A prefix parent is not dropped unless FV evidence proves a rollup."""
        df = self._make_bdc_df([
            {"investment_identifier": "Medallia, Inc.", "cik": "123",
             "accession_number": "001", "interest_rate": 11.0,
             "fair_value": 1000000},
            {"investment_identifier": "Medallia, Inc., Emerald JV LP",
             "cik": "123", "accession_number": "001",
             "interest_rate": 11.0, "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        ids = set(result["bdc_investment_identifier"])
        assert "Medallia, Inc." in ids
        assert "Medallia, Inc., Emerald JV LP" in ids

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

    def test_prefix_subtotal_no_fv_child_kept(self):
        """Row is NOT removed when the longer 'child' has no fair_value.

        CIK 845385 pattern: same position tagged twice -- once with FV
        ("Rockfish - First Lien Loan") and once with industry suffix but no
        FV ("Rockfish - First Lien Loan - Casual Dining").  The industry-
        tagged row is metadata only and should not trigger subtotal removal.
        """
        df = self._make_bdc_df([
            # Parent: has FV (should survive)
            {"investment_identifier": "Rockfish Seafood Grill, Inc. - First Lien Loan",
             "cik": "845", "accession_number": "A01",
             "fair_value": 6219954, "cost": 6500000},
            # Industry-tagged: has cost/rate but no FV (metadata only)
            {"investment_identifier":
             "Rockfish Seafood Grill, Inc. - First Lien Loan - Casual Dining",
             "cik": "845", "accession_number": "A01",
             "fair_value": "", "cost": 6500000, "interest_rate": 9.0},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Rockfish Seafood Grill, Inc."
        assert abs(result.iloc[0]["fair_value"] - 6219954) < 1

    def test_prefix_parent_with_one_fv_child_is_retained(self):
        """One child with matching FV is not enough to prove a subtotal."""
        df = self._make_bdc_df([
            {"investment_identifier": "Medallia, Inc.",
             "cik": "123", "accession_number": "001",
             "fair_value": 2000000},
            {"investment_identifier": "Medallia, Inc., First Lien Term Loan",
             "cik": "123", "accession_number": "001",
             "fair_value": 2000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        assert set(result["bdc_investment_identifier"]) == {
            "Medallia, Inc.",
            "Medallia, Inc., First Lien Term Loan",
        }

    def test_prefix_parent_with_two_children_summing_exactly_is_removed(self):
        """A prefix parent is dropped when two child rows exactly sum to it."""
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
        ids = set(result["bdc_investment_identifier"])
        assert "Kaseya Inc., First Lien" not in ids
        assert "Kaseya Inc., First Lien - Drawn 1" in ids
        assert "Kaseya Inc., First Lien - Undrawn 1" in ids

    def test_blackstone_cambium_parent_and_emerald_child_survive(self):
        """Cambium-style parent and Emerald JV child both survive absent rollup FV evidence."""
        df = self._make_bdc_df([
            {"investment_identifier": "Cambium Learning Group, Inc.",
             "cik": "123", "accession_number": "001",
             "fair_value": 2000000},
            {"investment_identifier": "Cambium Learning Group, Inc., Emerald JV LP",
             "cik": "123", "accession_number": "001",
             "fair_value": 250000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        assert set(result["bdc_investment_identifier"]) == {
            "Cambium Learning Group, Inc.",
            "Cambium Learning Group, Inc., Emerald JV LP",
        }

    def test_1000x_scale_correction(self):
        """CIK-quarter with 1000x inflated FV is auto-corrected to /1000."""
        rows = []
        # Normal quarters (4 of them)
        for rd in ["2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31"]:
            rows.append({
                "investment_identifier": "Del Real LLC - First Lien Term Loan",
                "cik": "9999", "entity_name": "Test BDC",
                "accession_number": f"ACC-{rd}", "form_type": "10-Q",
                "filing_date": rd, "report_date": rd,
                "fair_value": 40000000, "cost": 42000000,
                "principal_amount": 45000000,
            })
        # Inflated quarter: 1000x
        rows.append({
            "investment_identifier": "Del Real LLC - First Lien Term Loan",
            "cik": "9999", "entity_name": "Test BDC",
            "accession_number": "ACC-2023-03-31", "form_type": "10-Q",
            "filing_date": "2023-03-31", "report_date": "2023-03-31",
            "fair_value": 40000000000,  # 40B = 1000x of 40M
            "cost": 42000000000,
            "principal_amount": 45000000000,
        })
        df = self._make_bdc_df(rows)
        result = _prepare_bdc(df)
        inflated = result[result["report_date"].astype(str) == "2023-03-31"]
        assert len(inflated) == 1
        # After correction: FV should be ~40M, not 40B
        assert inflated.iloc[0]["fair_value"] < 1e9
        assert abs(inflated.iloc[0]["fair_value"] - 40000000) < 1
        assert abs(inflated.iloc[0]["cost"] - 42000000) < 1

    def test_1000x_scale_no_false_positive_on_growth(self):
        """CIK with only 2 quarters does NOT trigger scale correction."""
        rows = []
        # Just 2 quarters: one small, one large (genuine growth)
        rows.append({
            "investment_identifier": "GrowCo LLC - Term Loan",
            "cik": "8888", "entity_name": "Test BDC",
            "accession_number": "ACC-Q1", "form_type": "10-Q",
            "filing_date": "2023-03-31", "report_date": "2023-03-31",
            "fair_value": 1000000,
        })
        rows.append({
            "investment_identifier": "GrowCo LLC - Term Loan",
            "cik": "8888", "entity_name": "Test BDC",
            "accession_number": "ACC-Q2", "form_type": "10-Q",
            "filing_date": "2023-06-30", "report_date": "2023-06-30",
            "fair_value": 500000000,  # 500x but only 2 quarters
        })
        df = self._make_bdc_df(rows)
        result = _prepare_bdc(df)
        large = result[result["report_date"].astype(str) == "2023-06-30"]
        # Should NOT be corrected (only 2 quarters, guard prevents it)
        assert abs(large.iloc[0]["fair_value"] - 500000000) < 1

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

    def test_nonaccrual_columns_threaded_through(self):
        """nonaccrual_footnote/dimension columns survive staging to unified."""
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp - Term Loan",
             "cik": "123", "fair_value": 1000000,
             "nonaccrual_footnote": True, "nonaccrual_dimension": False},
            {"investment_identifier": "Beta Inc - Note",
             "cik": "123", "fair_value": 2000000,
             "nonaccrual_footnote": False, "nonaccrual_dimension": True},
            {"investment_identifier": "Gamma LLC - Revolver",
             "cik": "123", "fair_value": 500000,
             "nonaccrual_footnote": False, "nonaccrual_dimension": False},
        ])
        result = _prepare_bdc(df)
        assert "nonaccrual_footnote" in result.columns
        assert "nonaccrual_dimension" in result.columns

        by_issuer = result.set_index("issuer_name")
        # Footnote-flagged position
        acme = by_issuer.loc["Acme Corp"]
        assert acme["nonaccrual_footnote"] in (True, "true", "True", 1)
        # Dimension-flagged position
        beta = by_issuer.loc["Beta Inc"]
        assert beta["nonaccrual_dimension"] in (True, "true", "True", 1)
        # Clean position
        gamma = by_issuer.loc["Gamma LLC"]
        assert gamma["nonaccrual_footnote"] in (False, "false", "False", 0)
        assert gamma["nonaccrual_dimension"] in (False, "false", "False", 0)


# ---------------------------------------------------------------------------
# Amendment dedup in _prepare_bdc (CTE 1b)
# ---------------------------------------------------------------------------

class TestAmendmentDedup:
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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

    def test_placeholder_issuer_and_cusip_do_not_make_placeholder_position_key(self):
        df = self._make_nport_df([
            {
                "fair_value_level": "3",
                "cik": "200",
                "registrant_name": "Test Fund",
                "issuer_name": "NC",
                "issuer_title": "CHARGEPOINT Inc. Preferred F Shares",
                "issuer_cusip": "NC",
                "asset_cat": "EP",
                "issuer_type": "CORP",
                "currency_value": 900000,
            },
        ])
        result = _prepare_nport(df)
        assert result.iloc[0]["issuer_name"] == "CHARGEPOINT Inc. Preferred F Shares"
        key = result.iloc[0]["position_key"]
        assert "chargepoint" in key
        assert key != "nc nc"

    def test_issuer_cusip_is_not_entire_position_key(self):
        df = self._make_nport_df([
            {
                "fair_value_level": "3",
                "cik": "200",
                "registrant_name": "Test Fund",
                "issuer_name": "Global Medical Response",
                "issuer_title": "First Lien Term Loan",
                "issuer_cusip": "123456789",
                "asset_cat": "LON",
                "issuer_type": "CORP",
                "currency_value": 900000,
            },
        ])
        result = _prepare_nport(df)
        key = result.iloc[0]["position_key"]
        assert key != "123456789"
        assert "global medical response" in key
        assert "first lien term loan" in key

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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

    def test_libor_shorthand_extracted(self):
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan L+625, 1.00% Floor",
            "cik": "1", "fair_value": 1000000,
        }])
        result = _prepare_bdc(df)
        # "L+" shorthand detected as LIBOR
        assert result.iloc[0]["reference_rate_type"] == "LIBOR"

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
    pytestmark = SLOW_INTEGRATION_MARKS

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

    @pytest.mark.slow
    @pytest.mark.integration
    def test_full_integration(self, tmp_path):
        """End-to-end test with in-memory DataFrames."""
        bdc_df = self._make_bdc_df()
        nport_df = self._make_nport_df()

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test_output.csv"):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

        # 2 BDC (Acme Corp + Growth Fund) + 1 N-PORT (Private Borrower) = 3
        assert len(result) == 3

        # Check column count matches schema (row_id/row_id_basis are appended
        # as the final build step and live outside UNIFIED_COLUMNS by design)
        assert list(result.columns) == UNIFIED_COLUMNS + ["row_id", "row_id_basis"]
        assert result["row_id"].str.match(r"^ROW-[0-9a-f]{16}$").all()
        assert result["row_id"].nunique() == len(result)

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

    @pytest.mark.slow
    @pytest.mark.integration
    def test_ixbrl_lien_fills_blank_keyword_lien(self, tmp_path):
        """iXBRL section-header lien (staging lien_position, populated only by the
        reconciled field-status overlay) fills lien where the keyword classifier is
        blank; the keyword classifier still wins where both are present."""
        common = {
            "cik": "123", "entity_name": "Test BDC", "accession_number": "0001-23",
            "form_type": "10-K", "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "cost": 990000.0, "interest_rate": 8.5, "basis_spread": 3.5,
            "reference_rate_type": "SOFR", "maturity_date": "2028-01-15",
            "pct_of_net_assets": 0.05, "pik_rate": None, "shares_held": None,
            "unrealized_gain_loss": 10000.0,
            "investment_type": "", "industry": "", "affiliation": "", "period": "2023-03-31",
        }
        # The overlay keys on the FULL InvestmentIdentifierAxis member carried in
        # dimensions_raw (falling back to the identifier only when dims is absent),
        # so the fixture dims must hold the real member, not a placeholder.
        bdc_df = pd.DataFrame([
            # keyword-neutral DL row -> _sql_classify_lien NULL -> iXBRL fills it
            {**common, "investment_identifier": "Acme Holdings - Term Loan B",
             "dimensions_raw": "us-gaap:InvestmentIdentifierAxis=Acme Holdings - Term Loan B",
             "fair_value": 1000000.0, "principal_amount": 1000000.0},
            # keyword 'first lien' DL row -> keyword wins over the iXBRL value
            {**common, "investment_identifier": "Beta Corp - First Lien Term Loan",
             "dimensions_raw": "us-gaap:InvestmentIdentifierAxis=Beta Corp - First Lien Term Loan",
             "fair_value": 2000000.0, "principal_amount": 2000000.0},
        ])
        status = pd.DataFrame([
            {"cik": "123", "accession_number": "0001-23", "report_date": "2023-03-31",
             "raw_id_lower": "acme holdings - term loan b", "maturity_date": "",
             "maturity_status": "blank", "reference_rate_type": "",
             "reference_rate_status": "blank", "lien_position": "Second Lien",
             "lien_status": "value"},
            {"cik": "123", "accession_number": "0001-23", "report_date": "2023-03-31",
             "raw_id_lower": "beta corp - first lien term loan", "maturity_date": "",
             "maturity_status": "blank", "reference_rate_type": "",
             "reference_rate_status": "blank", "lien_position": "Second Lien",
             "lien_status": "value"},
        ])
        status_path = tmp_path / "field_status.csv"
        status.to_csv(status_path, index=False)
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE", tmp_path / "out.csv"), \
             patch("pipeline.config.BDC_IXBRL_FIELD_STATUS_FILE", status_path):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=self._make_nport_df())
        acme = result[result["issuer_name"].str.contains("Acme", case=False)].iloc[0]
        beta = result[result["issuer_name"].str.contains("Beta", case=False)].iloc[0]
        assert acme["index_classification"] == "DIRECT_LENDING"
        assert acme["lien_position"] == "Second Lien"   # iXBRL fallback filled blank keyword
        assert beta["lien_position"] == "First Lien"     # keyword classifier wins over iXBRL

    @pytest.mark.slow
    @pytest.mark.integration
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
             patch("pipeline.unified_holdings.BDC_HOLDINGS_PARQUET_FILE",
                   tmp_path / "missing_bdc.parquet"), \
             patch("pipeline.unified_holdings.NPORT_HOLDINGS_FILE", nport_path), \
             patch("pipeline.unified_holdings.NPORT_HOLDINGS_PARQUET_FILE",
                   tmp_path / "missing_nport.parquet"), \
             patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE", output_path):
            result = build_unified_holdings()

        assert len(result) == 3
        assert output_path.exists()


# ---------------------------------------------------------------------------
# Entity enrichment in build_unified_holdings
# ---------------------------------------------------------------------------

class TestEntityEnrichment:
    pytestmark = SLOW_INTEGRATION_MARKS

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

    @pytest.mark.slow
    @pytest.mark.integration
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

    @pytest.mark.slow
    @pytest.mark.integration
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

    @pytest.mark.slow
    @pytest.mark.integration
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

    @pytest.mark.slow
    @pytest.mark.integration
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

        # row_id/row_id_basis are appended after all enrichment layers,
        # outside UNIFIED_COLUMNS
        assert list(result.columns) == UNIFIED_COLUMNS + ["row_id", "row_id_basis"]


# ---------------------------------------------------------------------------
# Industry enrichment in build_unified_holdings
# ---------------------------------------------------------------------------

class TestIndustryEnrichment:
    pytestmark = SLOW_INTEGRATION_MARKS

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

    @pytest.mark.slow
    @pytest.mark.integration
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

    @pytest.mark.slow
    @pytest.mark.integration
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

    @pytest.mark.slow
    @pytest.mark.integration
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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
        from pipeline.staging_bdc import _prepare_bdc
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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
        assert result.iloc[0]["instrument_description"] == "1st Lien/Senior Secured Debt"

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
        assert result.iloc[0]["instrument_description"] == "Common Stock"

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

    def test_boundary_exactly_50(self):
        """50 is implausible as a percentage rate; treated as bps, /100 = 0.50."""
        assert _normalize_rate(50.0) == pytest.approx(0.50)

    def test_boundary_just_above_50(self):
        """50.01 is in the bps band (>=50), so /100 = 0.5001."""
        assert _normalize_rate(50.01) == pytest.approx(0.5001)

    def test_negative_decimal(self):
        """Negative rate (rare but possible) in decimal -> *100."""
        assert _normalize_rate(-0.02) == pytest.approx(-2.0)


class TestRateNormalizationSqlPath:
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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

    def test_nport_rate_exactly_50_capped_to_null(self):
        """annualized_rate=50 -> interest_rate is NULL (>= 50 boundary)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "annualized_rate": 50.0,
        }])
        result = _prepare_nport(df)
        assert pd.isna(result.iloc[0]["interest_rate"])

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_INTEGRATION_MARKS

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
    pytestmark = SLOW_INTEGRATION_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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

def _sql_classify(rows, include_index=False):
    """Helper: run exposure_type and asset_class SQL classification on test rows.

    Each row is a dict with keys: asset_category, issuer_category,
    issuer_name, instrument_description, nport_issuer_type (optional).
    Returns list of (exposure_type, asset_class) tuples, or
    (index_classification, exposure_type, asset_class) tuples when requested.
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
    idx_sql = _sql_classify_index()

    select_cols = f"{exp_sql} AS exposure_type, {ac_sql} AS asset_class"
    if include_index:
        select_cols = (
            f"{idx_sql} AS index_classification, "
            f"{exp_sql} AS exposure_type, {ac_sql} AS asset_class"
        )

    results = con.execute(f"""
        SELECT {select_cols}
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

    def test_asset_category_cash_routes_to_cash(self):
        """Rows staged with asset_category='CASH' classify as CASH / LIQUID
        regardless of issuer text -- this is the retained-cash bucket path."""
        result = _sql_classify([
            {"asset_category": "CASH", "issuer_category": "CORPORATE",
             "issuer_name": "First American Government Obligations Fund",
             "instrument_description": ""}
        ], include_index=True)
        index_classification, exposure_type, asset_class = result[0]
        assert index_classification == "CASH"
        assert asset_class == "CASH"
        assert exposure_type == "LIQUID"

    def test_asset_category_cash_does_not_affect_loans(self):
        """False-positive guard: a normal corporate loan is unaffected by the
        new asset_category='CASH' branch."""
        result = _sql_classify([
            {"asset_category": "LOAN", "issuer_category": "CORPORATE",
             "issuer_name": "Acme Corp", "instrument_description": "First Lien Term Loan"}
        ], include_index=True)
        index_classification, _exposure_type, asset_class = result[0]
        assert index_classification == "DIRECT_LENDING"
        assert asset_class == "PRIVATE_CREDIT"

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

    def test_nac_re_corporate_re_sql(self):
        """CORPORATE + nport_asset_cat=RE -> REAL_ESTATE (not PRIVATE_EQUITY)."""
        result = _sql_classify([
            {"asset_category": "EQUITY_COMMON", "issuer_category": "CORPORATE",
             "issuer_name": "Prime ST - HQ @ First",
             "instrument_description": "", "nport_asset_cat": "RE"}
        ])
        assert result[0][1] == "REAL_ESTATE"

    def test_nac_re_corporate_index_sql(self):
        """CORPORATE + nport_asset_cat=RE -> DIRECT_REAL_ESTATE index."""
        result = _sql_classify([
            {"asset_category": "EQUITY_COMMON", "issuer_category": "CORPORATE",
             "issuer_name": "Prime ST - HQ @ First",
             "instrument_description": "", "nport_asset_cat": "RE"}
        ], include_index=True)
        assert result[0][0] == "DIRECT_REAL_ESTATE"
        assert result[0][2] == "REAL_ESTATE"

    def test_nac_re_loan_corporate_stays_lending_sql(self):
        """LOAN + CORPORATE + nport_asset_cat=RE -> DIRECT_LENDING index, REAL_ESTATE asset_class."""
        result = _sql_classify([
            {"asset_category": "LOAN", "issuer_category": "CORPORATE",
             "issuer_name": "RE SPV Mortgage",
             "instrument_description": "", "nport_asset_cat": "RE"}
        ], include_index=True)
        assert result[0][0] == "DIRECT_LENDING"
        assert result[0][2] == "REAL_ESTATE"

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

    def test_bdc_vehicle_fund_sql_updates_index_and_asset_class(self):
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "Golub Capital BDC 4 Inc",
             "instrument_description": "", "nport_asset_cat": "EC"}
        ], include_index=True)
        assert result[0] == ("PRIVATE_CREDIT_FUND", "FUND", "PRIVATE_CREDIT")

    def test_bdc_advisory_fund_sql_excluded_from_bdc_vehicle_rule(self):
        result = _sql_classify([
            {"asset_category": "OTHER", "issuer_category": "FUND",
             "issuer_name": "Stellus Private BDC Advisory LLC",
             "instrument_description": "", "nport_asset_cat": "EC"}
        ], include_index=True)
        assert result[0] == ("PRIVATE_EQUITY_FUND", "FUND", "PRIVATE_EQUITY")


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

    def test_subordinate_note_structured_credit(self):
        result = _classify_index(
            "OTHER", "OTHER", "GPG Loan Funding, LL", "Subordinate Note"
        )
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

    def test_bdc_vehicle_fund_becomes_private_credit_fund(self):
        result = _classify_index(
            "OTHER", "FUND", "Golub Capital BDC 4 Inc", "", nport_asset_cat="EC"
        )
        assert result == "PRIVATE_CREDIT_FUND"

    def test_bdc_advisory_fund_uses_existing_fallback(self):
        result = _classify_index(
            "OTHER", "FUND", "Stellus Private BDC Advisory LLC", "", nport_asset_cat="EC"
        )
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

    def test_direct_real_estate_nac_re_equity(self):
        """CORPORATE + nport_asset_cat=RE + EQUITY_COMMON -> DIRECT_REAL_ESTATE."""
        result = _classify_index("EQUITY_COMMON", "CORPORATE",
                                 "Prime ST - HQ @ First", "",
                                 nport_asset_cat="RE")
        assert result == "DIRECT_REAL_ESTATE"

    def test_direct_real_estate_nac_re_preferred(self):
        """CORPORATE + nport_asset_cat=RE + EQUITY_PREFERRED -> DIRECT_REAL_ESTATE."""
        result = _classify_index("EQUITY_PREFERRED", "CORPORATE",
                                 "Industrial AIP-PMR 3-Pack", "",
                                 nport_asset_cat="RE")
        assert result == "DIRECT_REAL_ESTATE"

    def test_direct_lending_nac_re_loan(self):
        """LOAN + CORPORATE + nport_asset_cat=RE -> DIRECT_LENDING (loan takes priority)."""
        result = _classify_index("LOAN", "CORPORATE",
                                 "RE SPV Mortgage Loan", "",
                                 nport_asset_cat="RE")
        assert result == "DIRECT_LENDING"

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


class TestApplyUnclassifiedCache:
    def _make_unified_df(self, rows):
        data = []
        for row in rows:
            full_row = {c: "" for c in UNIFIED_COLUMNS}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_reclassifies_only_unclassified_and_flags_jv(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "unclassified_review_cache.csv"
        pd.DataFrame([
            {
                "name_norm": "alpha",
                "verdict": "CLASSIFIED",
                "confidence": "high",
                "new_index_classification": "DIRECT_LENDING",
                "asset_class": "LOAN",
            },
            {
                "name_norm": "beta",
                "verdict": "CLASSIFIED",
                "confidence": "high",
                "new_index_classification": "STRUCTURED_CREDIT",
                "asset_class": "LOAN",
            },
            {
                "name_norm": "gamma",
                "verdict": "JV_SUBSIDIARY",
                "confidence": "high",
                "new_index_classification": "",
                "asset_class": "",
            },
        ]).to_csv(cache_path, index=False)
        monkeypatch.setattr(
            "pipeline.unified_holdings.UNCLASSIFIED_REVIEW_CACHE_FILE",
            cache_path,
        )

        df = self._make_unified_df([
            {
                "issuer_name": "Alpha",
                "index_classification": "UNCLASSIFIED",
                "exposure_type": "OTHER",
                "asset_class": "OTHER",
            },
            {
                "issuer_name": "Beta",
                "index_classification": "PRIVATE_EQUITY",
                "exposure_type": "DIRECT",
                "asset_class": "PRIVATE_EQUITY",
            },
            {
                "issuer_name": "Gamma",
                "index_classification": "UNCLASSIFIED",
                "exposure_type": "OTHER",
                "asset_class": "OTHER",
            },
        ])

        result = _apply_unclassified_cache(df)

        assert result.loc[0, "index_classification"] == "DIRECT_LENDING"
        assert result.loc[0, "exposure_type"] == "DIRECT"
        assert result.loc[0, "asset_class"] == "PRIVATE_CREDIT"
        assert result.loc[1, "index_classification"] == "PRIVATE_EQUITY"
        assert result.loc[2, "jv_subsidiary"] == "Y"


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


class TestRestoreDeterministicClassificationRules:
    def test_subordinate_note_restored_after_stabilization(self):
        row = {col: "" for col in UNIFIED_COLUMNS}
        row.update({
            "cik": "0001234567",
            "source": "nport",
            "issuer_name": "GPG Loan Funding, LL Subordinate Note /",
            "instrument_description": "GPG Loan Funding, LL Subordinate Note /",
            "asset_category": "OTHER",
            "issuer_category": "CORPORATE",
            "nport_asset_cat": "ABS-MBS",
            "index_classification": "UNCLASSIFIED",
            "exposure_type": "DIRECT",
            "asset_class": "OTHER",
        })
        result = _restore_deterministic_classification_rules(
            pd.DataFrame([row])[UNIFIED_COLUMNS]
        )
        assert result.iloc[0]["index_classification"] == "STRUCTURED_CREDIT"
        assert result.iloc[0]["asset_class"] == "STRUCTURED_CREDIT"
        assert result.iloc[0]["exposure_type"] == "DIRECT"

    def test_bdc_vehicle_restored_after_stabilization(self):
        row = {col: "" for col in UNIFIED_COLUMNS}
        row.update({
            "cik": "0001234567",
            "source": "nport",
            "issuer_name": "GOLUB CAPITAL BDC 4, Inc. /",
            "instrument_description": "GOLUB CAPITAL BDC 4, Inc. /",
            "asset_category": "OTHER",
            "issuer_category": "FUND",
            "nport_asset_cat": "EC",
            "index_classification": "PRIVATE_EQUITY_FUND",
            "exposure_type": "FUND",
            "asset_class": "PRIVATE_EQUITY",
        })
        result = _restore_deterministic_classification_rules(
            pd.DataFrame([row])[UNIFIED_COLUMNS]
        )
        assert result.iloc[0]["index_classification"] == "PRIVATE_CREDIT_FUND"
        assert result.iloc[0]["asset_class"] == "PRIVATE_CREDIT"
        assert result.iloc[0]["exposure_type"] == "FUND"


class TestStabilizeClassificationMore:
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

    def test_same_borrower_different_instruments_do_not_leak(self):
        rows = []
        for i in range(4):
            row = {col: "" for col in UNIFIED_COLUMNS}
            row.update({
                "cik": "0001234567", "source": "bdc",
                "issuer_name": "Capital Southwest Style Borrower",
                "instrument_description": "First Lien Term Loan",
                "asset_category": "LOAN", "issuer_category": "CORPORATE",
                "report_date": f"2024-0{i+1}-30",
                "index_classification": "DIRECT_LENDING",
                "exposure_type": "DIRECT", "asset_class": "PRIVATE_CREDIT",
            })
            rows.append(row)
        for instrument, asset_category, index_class in [
            ("Common Equity", "EQUITY_COMMON", "COMMON_EQUITY"),
            ("Preferred Equity", "EQUITY_PREFERRED", "PREFERRED_EQUITY"),
        ]:
            row = {col: "" for col in UNIFIED_COLUMNS}
            row.update({
                "cik": "0001234567", "source": "bdc",
                "issuer_name": "Capital Southwest Style Borrower",
                "instrument_description": instrument,
                "asset_category": asset_category,
                "issuer_category": "CORPORATE",
                "report_date": "2024-06-30",
                "index_classification": index_class,
                "exposure_type": "DIRECT", "asset_class": "PRIVATE_EQUITY",
            })
            rows.append(row)

        result = _stabilize_classification(pd.DataFrame(rows)[UNIFIED_COLUMNS])
        equity = result[result["asset_category"].str.startswith("EQUITY")]
        assert equity["index_classification"].tolist() == [
            "COMMON_EQUITY", "PREFERRED_EQUITY",
        ]
        assert (equity["asset_class"] == "PRIVATE_EQUITY").all()

    def test_same_loan_punctuation_case_stabilizes(self):
        rows = []
        for report_date, instrument, index_class in [
            ("2023-03-31", "First-Lien Term Loan", "DIRECT_LENDING"),
            ("2023-06-30", "first lien term loan", "DIRECT_LENDING"),
            ("2023-09-30", "First Lien Term Loan", "DIRECT_LENDING"),
            ("2023-12-31", "FIRST LIEN TERM LOAN", "COMMON_EQUITY"),
        ]:
            row = {col: "" for col in UNIFIED_COLUMNS}
            row.update({
                "cik": "0001234567", "source": "bdc",
                "issuer_name": "Acme Corp",
                "instrument_description": instrument,
                "asset_category": "LOAN", "issuer_category": "CORPORATE",
                "report_date": report_date,
                "index_classification": index_class,
                "exposure_type": "DIRECT",
                "asset_class": (
                    "PRIVATE_CREDIT" if index_class == "DIRECT_LENDING"
                    else "PRIVATE_EQUITY"
                ),
            })
            rows.append(row)

        result = _stabilize_classification(pd.DataFrame(rows)[UNIFIED_COLUMNS])
        assert (result["index_classification"] == "DIRECT_LENDING").all()
        assert (result["asset_class"] == "PRIVATE_CREDIT").all()


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

    def test_trinity_type_of_investment_leaf_with_corporation_kept(self):
        assert not _is_bdc_aggregate_row(
            "Portfolio Company Debt Securities- United States Space Technology "
            "Astranis Space Technology Corporation Type of Investment Secured Loan "
            "Investment Date January 1, 2024 Maturity Date January 1, 2028 "
            "Interest Rate Fixed interest rate 10.0%"
        )

    def test_trinity_type_of_investment_leaf_with_limited_kept(self):
        assert not _is_bdc_aggregate_row(
            "Portfolio Company Debt Securities- Europe Industrials Example Limited "
            "Type of Investment Equipment Financing Investment Date March 31, 2022 "
            "Maturity Date April 1, 2025 Interest Rate Fixed interest rate 9.0%"
        )

    def test_trinity_type_of_investment_leaf_with_holding_company_kept(self):
        assert not _is_bdc_aggregate_row(
            "Portfolio Company Debt Securities- United States Education Technology "
            "Total Medical Sales Training Holding Company Type of Investment Secured Loan "
            "Investment Date January 1, 2024 Maturity Date January 1, 2028 "
            "Interest Rate Fixed interest rate 10.0%"
        )

    def test_trinity_bare_category_still_aggregate(self):
        assert _is_bdc_aggregate_row(
            "Portfolio Company Debt Securities- Europe Space Technology"
        )

    def test_trinity_subtotal_still_aggregate(self):
        assert _is_bdc_aggregate_row(
            "Portfolio Company Debt Securities- Sub-total: Education Technology"
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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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

    def test_subsidiary_detected_equity_method_investee_axis(self):
        """JV look-through facts on the equity-method-investee axis are flagged
        (same retain-and-flag treatment as the subsidiary axes; adjudicated
        2026-07-21/22, data_investigation_results parts 5-8)."""
        rows = [self._make_bdc_row(
            dimensions_raw=(
                "scheduleofequitymethodinvestmentequitymethodinvesteenameaxis=UltraIiiMember"
                "|investmentidentifieraxis=Bright Light Buyer, Inc. 1"
            ),
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
    pytestmark = SLOW_INTEGRATION_MARKS

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

    def test_preserves_same_issuer_distinct_subsidiary_position(self, tmp_path):
        """Same-issuer subsidiary rows are kept when economics differ."""
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
             "investment_identifier": "Acme Corp - First Lien",
             "fair_value": 250000.0, "cost": 249000.0,
             "principal_amount": 250000.0, "interest_rate": 8.5,
             "basis_spread": 3.5,
             "dimensions_raw": "nonconsolidatedsubsidiaryaxis=JV1",
             "period": "2023-03-31"},
        ])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test.csv"):
            result = build_unified_holdings(
                bdc_df=bdc_df, nport_df=pd.DataFrame())

        acme = result[result["issuer_name"] == "Acme Corp"]
        assert len(acme) == 2
        assert set(acme["fair_value"].astype(float)) == {1000000.0, 250000.0}
        assert set(acme["is_subsidiary"].astype(int)) == {0, 1}

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
# BDC dimension-path duplicate dedup in build_unified_holdings
# ---------------------------------------------------------------------------

class TestDimensionPathDedup:
    pytestmark = SLOW_INTEGRATION_MARKS

    """Tests for BDC-only dimension-path duplicate handling."""

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
            full_row.update({
                "cik": "0000000200",
                "entity_name": "Test BDC",
                "accession_number": "acc1",
                "form_type": "10-K",
                "filing_date": "2023-06-01",
                "report_date": "2023-03-31",
                "period": "2023-03-31",
                "dimensions_raw": "investmentaxis=member",
            })
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
            "quarter", "balance", "unit", "other_unit_desc", "exchange_rate",
            "other_asset", "other_issuer", "sub_type", "derivative_cat",
            "is_default", "other_identifier", "currency_code",
            "liquidity_classification", "are_any_interest_payment",
            "is_any_portion_interest_paid",
        ]
        data = []
        for i, row in enumerate(rows, start=1):
            full_row = {c: "" for c in cols}
            full_row.update({
                "accession_number": "nport-acc",
                "holding_id": f"H{i:03d}",
                "issuer_lei": "",
                "issuer_cusip": "",
                "currency_value": 1000000.0,
                "percentage": 0.01,
                "asset_cat": "LON",
                "issuer_type": "CORP",
                "investment_country": "US",
                "is_restricted_security": "Y",
                "fair_value_level": 3,
                "annualized_rate": 9.0,
                "payoff_profile": "Long",
                "cik": "0000000300",
                "registrant_name": "Test Fund",
                "filing_date": "2023-05-31",
                "report_date": "2023-03-31",
                "series_name": "Test Series",
                "series_id": "S001",
                "quarter": "2023q1",
                "balance": 1000000.0,
                "unit": "PA",
                "currency_code": "USD",
            })
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def _build(self, tmp_path, bdc_rows=None, nport_rows=None):
        bdc_df = self._make_bdc_df(bdc_rows or [])
        nport_df = self._make_nport_df(nport_rows or [])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                   tmp_path / "test.csv"):
            return build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)

    def test_case_variant_same_fv_different_cost_collapses(self, tmp_path):
        result = self._build(tmp_path, bdc_rows=[
            {"investment_identifier": "ARBORWORKS, LLC - Term Loan",
             "fair_value": 1000000.0, "cost": 900000.0,
             "principal_amount": 1000000.0},
            {"investment_identifier": "ArborWorks, LLC - Term Loan",
             "fair_value": 1000000.0, "cost": 950000.0,
             "principal_amount": 1000000.0},
        ])
        rows = result[result["issuer_name"].str.contains("arborworks", case=False)]
        assert len(rows) == 1

    def test_punctuation_variant_same_position_collapses(self, tmp_path):
        result = self._build(tmp_path, bdc_rows=[
            {"investment_identifier": "Celebration Bidco, LLC ,Common Stock",
             "fair_value": 250000.0, "cost": 200000.0,
             "shares_held": 1000.0},
            {"investment_identifier": "Celebration Bidco, LLC, Common Stock",
             "fair_value": 250000.0, "cost": 210000.0,
             "shares_held": 1000.0},
        ])
        rows = result[result["issuer_name"].str.contains("Celebration Bidco")]
        assert len(rows) == 1

    def test_same_issuer_fv_different_tranches_preserved(self, tmp_path):
        result = self._build(tmp_path, bdc_rows=[
            {"investment_identifier": "Acme Corp - Term Loan A",
             "fair_value": 1000000.0, "cost": 990000.0,
             "principal_amount": 1000000.0},
            {"investment_identifier": "Acme Corp - Term Loan B",
             "fair_value": 1000000.0, "cost": 990000.0,
             "principal_amount": 1000000.0},
        ])
        acme = result[result["issuer_name"] == "Acme Corp"]
        assert len(acme) == 2
        assert set(acme["instrument_description"]) == {"Term Loan A", "Term Loan B"}

    def test_same_issuer_fv_different_shares_preserved(self, tmp_path):
        result = self._build(tmp_path, bdc_rows=[
            {"investment_identifier": "Acme Corp - Common Stock",
             "fair_value": 1000000.0, "cost": 900000.0,
             "shares_held": 1000.0},
            {"investment_identifier": "Acme Corp - Common Stock",
             "fair_value": 1000000.0, "cost": 900000.0,
             "shares_held": 2000.0},
        ])
        acme = result[result["issuer_name"] == "Acme Corp"]
        assert len(acme) == 2

    def test_same_issuer_different_fv_preserved(self, tmp_path):
        result = self._build(tmp_path, bdc_rows=[
            {"investment_identifier": "Acme Corp - Term Loan",
             "fair_value": 1000000.0, "cost": 990000.0,
             "principal_amount": 1000000.0},
            {"investment_identifier": "Acme Corp - Term Loan",
             "fair_value": 1100000.0, "cost": 990000.0,
             "principal_amount": 1000000.0},
        ])
        acme = result[result["issuer_name"] == "Acme Corp"]
        assert len(acme) == 2

    def test_nport_distinct_cusip_not_collapsed(self, tmp_path):
        """N-PORT rows with same normalized issuer but different CUSIPs are
        genuinely distinct positions and must be preserved."""
        result = self._build(tmp_path, nport_rows=[
            {"holding_id": "H001", "issuer_name": "ArborWorks, LLC",
             "issuer_title": "Term Loan", "currency_value": 1000000.0,
             "balance": 1000000.0, "issuer_cusip": "00300H105"},
            {"holding_id": "H002", "issuer_name": "ARBORWORKS LLC",
             "issuer_title": "Term Loan", "currency_value": 1000000.0,
             "balance": 1000000.0, "issuer_cusip": "00300H204"},
        ])
        nport = result[result["source"] == "nport"]
        assert len(nport) == 2

    def test_nport_same_key_cross_quarter_collapsed(self, tmp_path):
        """N-PORT rows that are cross-quarter duplicates (same position in two
        quarterly bulk datasets) should be collapsed to one."""
        result = self._build(tmp_path, nport_rows=[
            {"holding_id": "H001", "issuer_name": "ArborWorks, LLC",
             "issuer_title": "Term Loan", "currency_value": 1000000.0,
             "balance": 1000000.0, "quarter": "2023q1",
             "accession_number": "acc-q1"},
            {"holding_id": "H002", "issuer_name": "ArborWorks, LLC",
             "issuer_title": "Term Loan", "currency_value": 1000000.0,
             "balance": 1000000.0, "quarter": "2023q2",
             "accession_number": "acc-q2"},
        ])
        nport = result[result["source"] == "nport"]
        assert len(nport) == 1

    def test_nport_case_variant_same_filing_collapsed(self, tmp_path):
        """N-PORT rows with same normalized key within the same filing
        are duplicates and should be collapsed."""
        result = self._build(tmp_path, nport_rows=[
            {"holding_id": "H001", "issuer_name": "ArborWorks, LLC",
             "issuer_title": "Term Loan", "currency_value": 1000000.0,
             "balance": 1000000.0},
            {"holding_id": "H002", "issuer_name": "ARBORWORKS LLC",
             "issuer_title": "Term Loan", "currency_value": 1000000.0,
             "balance": 1000000.0},
        ])
        nport = result[result["source"] == "nport"]
        assert len(nport) == 1

    def test_nport_distinct_maturity_not_collapsed(self, tmp_path):
        """N-PORT rows with same issuer/FV but different maturity dates are
        different tranches and must be preserved."""
        result = self._build(tmp_path, nport_rows=[
            {"holding_id": "H001", "issuer_name": "Acme Corp",
             "issuer_title": "Term Loan", "currency_value": 1000000.0,
             "balance": 1000000.0, "maturity_date": "2027-01-15"},
            {"holding_id": "H002", "issuer_name": "Acme Corp",
             "issuer_title": "Term Loan", "currency_value": 1000000.0,
             "balance": 1000000.0, "maturity_date": "2028-07-15"},
        ])
        nport = result[result["source"] == "nport"]
        assert len(nport) == 2

    def test_nport_distinct_asset_cat_not_collapsed(self, tmp_path):
        """N-PORT rows with same issuer/FV but different asset categories are
        different security types and must be preserved."""
        result = self._build(tmp_path, nport_rows=[
            {"holding_id": "H001", "issuer_name": "Acme Corp",
             "issuer_title": "Acme Corp", "currency_value": 1000000.0,
             "balance": 1000000.0, "asset_cat": "EC"},
            {"holding_id": "H002", "issuer_name": "Acme Corp",
             "issuer_title": "Acme Corp", "currency_value": 1000000.0,
             "balance": 1000000.0, "asset_cat": "LON"},
        ])
        nport = result[result["source"] == "nport"]
        assert len(nport) == 2


# ---------------------------------------------------------------------------
# Affiliation prefix stripping tests
# ---------------------------------------------------------------------------


class TestAffiliationPrefixStrip:
    pytestmark = SLOW_STAGING_SQL_MARKS

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
    pytestmark = SLOW_STAGING_SQL_MARKS

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

    def test_keep_same_issuer_same_fv_different_tranches(self):
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - Term Loan A",
             "fair_value": 1000000, "cost": 990000,
             "principal_amount": 1000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - Term Loan B",
             "fair_value": 1000000, "cost": 990000,
             "principal_amount": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        assert set(result["instrument_description"]) == {"Term Loan A", "Term Loan B"}

    def test_dedup_same_position_across_affiliation_members(self):
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier": "Acme Corp - Term Loan",
             "fair_value": 1000000, "cost": 990000,
             "principal_amount": 1000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2023-06-01", "report_date": "2023-03-31",
             "investment_identifier":
                 "Affiliated Investments - Acme Corp - Term Loan",
             "fair_value": 1000000, "cost": 990000,
             "principal_amount": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["bdc_investment_identifier"] == "Acme Corp - Term Loan"

    # -- Prefix-identifier dedup (sector subtotal / dimension-path dupes) ------

    def test_prefix_dedup_removes_sector_subtotal(self):
        """Sector subtotal with same FV as detail row is removed."""
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "Senior Secured Loans - IT Consulting",
             "fair_value": 12000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier":
                 "Senior Secured Loans - IT Consulting - Macrosoft Inc - Term Loan",
             "fair_value": 12000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert "Macrosoft" in result.iloc[0]["bdc_investment_identifier"]

    def test_prefix_dedup_removes_bare_issuer_subtotal(self):
        """Bare issuer name with same FV as detail row is removed."""
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "NSG Captive, Inc.",
             "fair_value": 48000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "NSG Captive, Inc. - Insurance - Equity",
             "fair_value": 48000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert "Insurance" in result.iloc[0]["bdc_investment_identifier"]

    def test_prefix_dedup_keeps_different_fv(self):
        """Parent and child with different FV are both kept."""
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "Acme Corp",
             "fair_value": 50000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "Acme Corp - Term Loan",
             "fair_value": 30000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2

    def test_prefix_dedup_keeps_non_prefix_same_fv(self):
        """Two rows with same FV but no prefix relationship are both kept."""
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "Acme Corp - Term Loan A",
             "fair_value": 10000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "Acme Corp - Term Loan B",
             "fair_value": 10000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2

    def test_prefix_dedup_chain_removes_all_intermediates(self):
        """Three-level chain A -> B -> C: both A and B are removed."""
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "Common Stock",
             "fair_value": 4000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "Common Stock - AI Sector",
             "fair_value": 4000000},
            {"cik": "200", "entity_name": "Test BDC",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier":
                 "Common Stock - AI Sector - Infinity Corp - SAFE",
             "fair_value": 4000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert "Infinity" in result.iloc[0]["bdc_investment_identifier"]

    def test_prefix_dedup_cross_cik_no_removal(self):
        """Same prefix+FV across different CIKs does not trigger removal."""
        df = self._make_bdc_df([
            {"cik": "200", "entity_name": "Fund A",
             "accession_number": "acc1", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "Acme Corp",
             "fair_value": 10000000},
            {"cik": "300", "entity_name": "Fund B",
             "accession_number": "acc2", "form_type": "10-K",
             "filing_date": "2025-06-01", "report_date": "2025-12-31",
             "investment_identifier": "Acme Corp - Term Loan",
             "fair_value": 10000000},
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


# ---------------------------------------------------------------------------
# Universe gating for index-facing unified holdings
# ---------------------------------------------------------------------------

class TestUniverseGate:
    def _make_unified_rows(self, rows):
        data = []
        for row in rows:
            full = {col: "" for col in UNIFIED_COLUMNS}
            full.update({
                "source": "nport",
                "cik": "0000000100",
                "entity_name": "Test Fund",
                "report_date": "2024-03-31",
                "issuer_name": "Acme Corp",
                "fair_value": "1000000",
                "asset_category": "LOAN",
                "issuer_category": "CORPORATE",
                "index_classification": "DIRECT_LENDING",
                "exposure_type": "DIRECT",
                "asset_class": "PRIVATE_CREDIT",
            })
            full.update(row)
            data.append(full)
        return pd.DataFrame(data, columns=UNIFIED_COLUMNS)

    def test_non_universe_nport_holdings_excluded_and_reported(self, tmp_path):
        holdings = self._make_unified_rows([
            {"cik": "100", "entity_name": "In Universe", "fair_value": "10"},
            {"cik": "2040315", "entity_name": "Needs Verification", "fair_value": "25"},
        ])
        universe_path = tmp_path / "combined_universe.csv"
        orphan_path = tmp_path / "universe_orphan_holdings.csv"
        pd.DataFrame([{"cik": "0000000100", "entity_name": "In Universe"}]).to_csv(
            universe_path, index=False
        )

        result = _apply_universe_gate(
            holdings,
            universe_path=universe_path,
            orphan_path=orphan_path,
        )
        orphans = pd.read_csv(orphan_path, dtype=str)

        assert set(result["cik"]) == {"0000000100"}
        assert orphans.iloc[0]["cik"] == "0002040315"
        assert orphans.iloc[0]["row_count"] == "1"
        assert orphans.iloc[0]["reason"] == "cik_absent_from_combined_universe"

    def test_missing_universe_file_keeps_rows_but_writes_empty_report(self, tmp_path):
        holdings = self._make_unified_rows([{"cik": "2040315"}])
        orphan_path = tmp_path / "universe_orphan_holdings.csv"

        result = _apply_universe_gate(
            holdings,
            universe_path=tmp_path / "missing.csv",
            orphan_path=orphan_path,
        )

        assert len(result) == 1
        assert list(pd.read_csv(orphan_path).columns) == [
            "cik", "entity_name", "source", "first_report_date",
            "last_report_date", "row_count", "fair_value", "reason",
        ]


def test_nport_exclude_cik_filtered_at_extraction_time():
    """NPORT_EXCLUDE_CIKS are excluded at extraction time in nport_holdings.py,
    not at staging/unified time.  Verify the extraction entry point removes them
    from target_ciks before processing any quarters."""
    from pipeline.config import NPORT_EXCLUDE_CIKS

    # Simulate a fund universe that includes an excluded CIK
    universe = pd.DataFrame({"cik": ["1547580", "9999999"]})
    with patch("pipeline.nport_holdings.FUND_UNIVERSE_FILE"), \
         patch("pipeline.nport_holdings._process_all_quarters") as mock_proc, \
         patch("pipeline.nport_holdings._supplement_from_xml"):
        mock_proc.return_value = (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        from pipeline.nport_holdings import extract_nport_holdings
        from pipeline.edgar_client import EdgarClient
        extract_nport_holdings(
            client=EdgarClient.__new__(EdgarClient),
            fund_universe=universe,
        )
        # The target_ciks passed to _process_all_quarters should exclude 1547580
        called_ciks = mock_proc.call_args[0][1]
        assert "1547580" not in called_ciks
        assert "9999999" in called_ciks


def test_total_investments_at_fair_value_is_aggregate_header():
    assert _is_bdc_aggregate_row("Total Investments at Fair Value")
    assert not _is_bdc_aggregate_row("Total Expert Inc.")


# ---------------------------------------------------------------------------
# Fix X06: principal_amount nulled for equity positions
# ---------------------------------------------------------------------------

class TestEquityPrincipalAmountNulled:
    pytestmark = SLOW_INTEGRATION_MARKS

    """Equity positions should have principal_amount = NULL in unified output.

    XBRL parser sometimes maps non-dollar facts (shares, percentages) to
    principal_amount for equity positions where par/principal is meaningless.
    """

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
            full_row["period"] = ""
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_equity_position_pa_nulled(self, tmp_path):
        """Equity position with spurious PA should have PA = NULL in output."""
        bdc_df = self._make_bdc_df([{
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Acme Corp - Common Stock",
            "fair_value": 394000.0, "cost": 352000.0,
            "principal_amount": 351500000.0,  # spurious
            "shares_held": 50000, "period": "2023-03-31",
        }])
        nport_df = pd.DataFrame()
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test_output.csv"):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)
        row = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert row["index_classification"] == "COMMON_EQUITY"
        assert pd.isna(row["principal_amount"])

    def test_preferred_equity_pa_nulled(self, tmp_path):
        """PREFERRED_EQUITY position with PA should have PA = NULL."""
        bdc_df = self._make_bdc_df([{
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Acme Corp - Preferred Stock",
            "fair_value": 500000.0, "cost": 480000.0,
            "principal_amount": 999999.0,  # spurious
            "shares_held": 10000, "period": "2023-03-31",
        }])
        nport_df = pd.DataFrame()
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test_output.csv"):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)
        row = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert row["index_classification"] == "PREFERRED_EQUITY"
        assert pd.isna(row["principal_amount"])

    def test_fund_position_pa_nulled(self, tmp_path):
        """FUND positions with spurious PA should have PA = NULL."""
        bdc_df = self._make_bdc_df([{
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "WhiteHawk Evergreen Fund, LP - LP Interest",
            "fair_value": 7664000.0, "cost": 7500000.0,
            "principal_amount": 7500000000.0,  # spurious 1000x
            "shares_held": "", "period": "2023-03-31",
        }])
        nport_df = pd.DataFrame()
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test_output.csv"):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)
        row = result[result["issuer_name"].str.contains("WhiteHawk")].iloc[0]
        assert row["index_classification"] == "PRIVATE_EQUITY_FUND"
        assert pd.isna(row["principal_amount"])

    def test_debt_position_pa_preserved(self, tmp_path):
        """Debt position with valid PA should keep PA intact."""
        bdc_df = self._make_bdc_df([{
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "fair_value": 1000000.0, "cost": 990000.0,
            "principal_amount": 1000000.0,
            "interest_rate": 8.5, "basis_spread": 3.5,
            "reference_rate_type": "SOFR",
            "maturity_date": "2028-01-15", "period": "2023-03-31",
        }])
        nport_df = pd.DataFrame()
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test_output.csv"):
            result = build_unified_holdings(bdc_df=bdc_df, nport_df=nport_df)
        row = result[result["issuer_name"] == "Acme Corp"].iloc[0]
        assert row["index_classification"] == "DIRECT_LENDING"
        assert float(row["principal_amount"]) == 1000000.0


@pytest.mark.slow
@pytest.mark.staging_sql
def test_prepare_bdc_converts_non_usd_principal_with_reference_fx(tmp_path, monkeypatch):
    fx_file = tmp_path / "fx_rates.csv"
    fx_file.write_text(
        "currency,rate_date,usd_per_currency,source,source_detail\n"
        "CAD,2024-03-31,0.75,test,fixture\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pipeline.staging_bdc.FX_RATES_FILE", fx_file)

    df = pd.DataFrame([{
        "cik": "123",
        "entity_name": "Test BDC",
        "accession_number": "0001-24",
        "form_type": "10-Q",
        "filing_date": "2024-05-01",
        "report_date": "2024-03-31",
        "period": "2024-03-31",
        "investment_identifier": "Acme Corp - First Lien Term Loan",
        "fair_value": 740.0,
        "cost": 730.0,
        "principal_amount": 1000.0,
        "principal_amount_unit": "cad",
        "fair_value_unit": "usd",
        "cost_unit": "usd",
        "shares_held": "",
        "interest_rate": 8.5,
        "basis_spread": 3.0,
        "pik_rate": "",
        "pct_of_net_assets": "",
        "unrealized_gain_loss": "",
        "maturity_date": "",
        "reference_rate_type": "",
        "dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
        "industry": "",
        "investment_type": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)
    row = result.iloc[0]
    assert row["principal_amount"] == 1000.0
    assert row["principal_amount_currency"] == "CAD"
    assert row["principal_amount_usd"] == 750.0
    assert row["principal_fx_rate_to_usd"] == 0.75
    assert row["principal_fx_status"] == "reference_fx"
    assert row["fair_value_currency"] == "USD"
    assert row["cost_currency"] == "USD"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_prepare_bdc_flags_missing_reference_fx(tmp_path, monkeypatch):
    fx_file = tmp_path / "fx_rates.csv"
    fx_file.write_text(
        "currency,rate_date,usd_per_currency,source,source_detail\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pipeline.staging_bdc.FX_RATES_FILE", fx_file)

    df = pd.DataFrame([{
        "cik": "123",
        "entity_name": "Test BDC",
        "accession_number": "0001-24",
        "form_type": "10-Q",
        "filing_date": "2024-05-01",
        "report_date": "2024-03-31",
        "period": "2024-03-31",
        "investment_identifier": "Acme Corp - First Lien Term Loan",
        "fair_value": 740.0,
        "cost": 730.0,
        "principal_amount": 1000.0,
        "principal_amount_unit": "eur",
        "fair_value_unit": "usd",
        "cost_unit": "usd",
        "shares_held": "",
        "interest_rate": 8.5,
        "basis_spread": 3.0,
        "pik_rate": "",
        "pct_of_net_assets": "",
        "unrealized_gain_loss": "",
        "maturity_date": "",
        "reference_rate_type": "",
        "dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
        "industry": "",
        "investment_type": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)
    row = result.iloc[0]
    assert row["principal_amount_currency"] == "EUR"
    assert pd.isna(row["principal_amount_usd"])
    assert row["principal_fx_status"] == "missing_reference_fx"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_prepare_nport_converts_non_usd_balance_with_exchange_rate():
    cols = [
        "accession_number", "holding_id", "issuer_name", "issuer_lei",
        "issuer_title", "issuer_cusip", "currency_value", "percentage",
        "asset_cat", "issuer_type", "investment_country",
        "is_restricted_security", "fair_value_level", "maturity_date",
        "coupon_type", "annualized_rate", "identifier_isin",
        "identifier_ticker", "payoff_profile", "cik", "registrant_name",
        "filing_date", "report_date", "series_name", "series_id",
        "quarter", "balance", "unit", "currency_code", "exchange_rate",
    ]
    row = {c: "" for c in cols}
    row.update({
        "cik": "123",
        "registrant_name": "Test Fund",
        "issuer_name": "Acme Corp",
        "issuer_title": "Term Loan",
        "currency_value": 750.0,
        "asset_cat": "LON",
        "issuer_type": "CORP",
        "fair_value_level": "3",
        "report_date": "2024-03-31",
        "balance": 1000.0,
        "unit": "PA",
        "currency_code": "CAD",
        "exchange_rate": 1.25,
    })

    result = _prepare_nport(pd.DataFrame([row]))
    out = result.iloc[0]
    assert out["principal_amount"] == 1000.0
    assert out["principal_amount_currency"] == "CAD"
    assert out["principal_amount_usd"] == 800.0
    assert out["principal_fx_status"] == "nport_exchange_rate"


# ---------------------------------------------------------------------------
# Percentage-prefix category subtotal aggregate detection
# ---------------------------------------------------------------------------

class TestPctPrefixCategorySubtotals:
    """Percentage-prefix category subtotals like '177.4% Common Equity/...'
    should be detected as aggregate rows."""

    def test_pct_prefix_slash_category_is_aggregate(self):
        """'177.4% Common Equity/Partnership Interests/Warrants' -> aggregate."""
        assert _is_bdc_aggregate_row(
            "177.4% Common Equity/Partnership Interests/Warrants"
        )

    def test_pct_prefix_first_lien_slash_is_aggregate(self):
        """'148.3% First Lien/Senior Secured Debt' -> aggregate."""
        assert _is_bdc_aggregate_row(
            "148.3% First Lien/Senior Secured Debt"
        )

    def test_pct_prefix_with_entity_signal_not_aggregate(self):
        """'89.2% FedHC InvestCo LP' has entity signal 'LP' -> NOT aggregate."""
        assert not _is_bdc_aggregate_row(
            "89.2% FedHC InvestCo LP"
        )

    def test_pct_prefix_with_dash_separator_not_aggregate(self):
        """'229.3% - Company Name - Instrument' has dash -> NOT aggregate."""
        assert not _is_bdc_aggregate_row(
            "229.3% - Company Name - Instrument"
        )

    def test_pct_prefix_with_llc_not_aggregate(self):
        """'95.93% Company LLC Industry Software' has entity 'LLC' -> NOT aggregate."""
        assert not _is_bdc_aggregate_row(
            "95.93% Company LLC Industry Software"
        )

    def test_pennantpark_real_equity_position_kept(self):
        """PennantPark real equity position with pct prefix but entity signal."""
        assert not _is_bdc_aggregate_row(
            "160.9% North Haven Saints Equity Holdings, LP Business Services"
        )

    def test_aggregate_pattern_common_equity_partnership(self):
        """'common equity/partnership interests' substring pattern matches."""
        assert _is_bdc_aggregate_row(
            "Common Equity/Partnership Interests Total"
        )

    def test_crescent_leaf_hierarchy_not_aggregate(self):
        assert not _is_bdc_aggregate_row(
            "Investments Australia Debt Investments Retailing "
            "Greencross (Vermont Aus Pty Ltd) Investment Type Unitranche "
            "First Lien Term Loan Interest Term B + 575 Interest Rate 9.52% "
            "Maturity/ Dissolution Date 03/2028"
        )

    def test_instrument_leaf_hierarchy_not_aggregate(self):
        assert not _is_bdc_aggregate_row(
            "Debt Investments Aerospace & Defense Kaman Corporation "
            "Instrument First Lien Term Loan Ref SOFR(Q) Spread 2.75% "
            "Total Coupon 7.07% Maturity 1/30/2032"
        )

    def test_debt_investments_pct_rollup_still_aggregate(self):
        assert _is_bdc_aggregate_row("Debt Investments (184.96%)")

    def test_investment_country_pct_rollup_still_aggregate(self):
        assert _is_bdc_aggregate_row("Investment United States - 141.4%")

    def test_instrument_word_without_leaf_terms_still_aggregate(self):
        assert _is_bdc_aggregate_row("Debt Investments Aerospace & Defense Instrument")

    def test_total_safety_holdings_not_aggregate(self):
        assert not _is_bdc_aggregate_row("Total Safety Holdings LLC")

    def test_generic_crescent_style_header_without_leaf_evidence_aggregate(self):
        assert _is_bdc_aggregate_row("Investments Canada Debt Investments")

    def test_no_dash_hierarchy_leaf_with_rate_evidence_not_aggregate(self):
        assert not _is_bdc_aggregate_row(
            "Debt Investments Business Services OutSystems Luxco SARL "
            "First-lien loan (EUR 3,263 par, due 12/2028) Initial Acquisition Date "
            "12/8/2022 Reference Rate and Spread E + 5.75% Interest Rate 8.74%"
        )


# ---------------------------------------------------------------------------
# Pct-prefix identifier parsing (PennantPark / Blue Owl / Saratoga)
# ---------------------------------------------------------------------------

class TestPctPrefixParsing:
    """Percentage-prefix category identifiers should skip the category segment
    and extract the real company name from the next segment."""

    def test_pennantpark_dash_format(self):
        """PennantPark: 'NNN.N% Category - NNN.N% Issuer Name Company Maturity ...'"""
        issuer, instrument = _parse_bdc_identifier(
            "184.3% First Lien Secured Debt - 112.9% Issuer Name "
            "Seaway Buyer, LLC Maturity 06/13/2029 Industry Chemicals"
        )
        assert issuer == "Seaway Buyer, LLC"
        assert "First Lien Secured Debt" in instrument

    def test_pennantpark_dash_no_issuer_label(self):
        """PennantPark without 'Issuer Name' label: company follows pct prefix."""
        issuer, instrument = _parse_bdc_identifier(
            "148.3% First Lien/Senior Secured Debt - 95.93% "
            "Company LLC Industry Software"
        )
        assert issuer == "Company LLC"
        assert "First Lien/Senior Secured Debt" in instrument

    def test_pennantpark_emdash_format(self):
        """PennantPark em-dash variant (U+2014) should be normalised to ' - '."""
        issuer, instrument = _parse_bdc_identifier(
            "177.4% Common Equity/Partnership Interests/Warrants"
            "\u2014"
            "23.0% SP L2 Holdings, LLC Industry Consumer Products"
        )
        assert issuer == "SP L2 Holdings, LLC"
        assert "Common Equity/Partnership Interests/Warrants" in instrument

    def test_pennantpark_emdash_no_keyword_boundary(self):
        """Em-dash variant without keyword boundary: entire text after pct is issuer."""
        issuer, instrument = _parse_bdc_identifier(
            "177.4% Common Equity/Partnership Interests/Warrants"
            "\u2014"
            "23.0% SP L2 Holdings, LLC Consumer Products"
        )
        # No keyword boundary -> entire text becomes issuer
        assert "SP L2 Holdings, LLC" in issuer
        assert "Common Equity/Partnership Interests/Warrants" in instrument

    def test_no_dash_issuer_name_label(self):
        """No-dash format with 'Issuer Name' label boundary."""
        issuer, instrument = _parse_bdc_identifier(
            "Common Equity/Partnership Interests/Warrants "
            "Issuer Name SP L2 Holdings, LLC Industry Consumer Products"
        )
        assert issuer == "SP L2 Holdings, LLC"
        assert "Common Equity/Partnership Interests/Warrants" in instrument

    def test_blue_owl_geography_with_industry(self):
        """Blue Owl CIK 1817825: pct + geography + industry + company."""
        issuer, instrument = _parse_bdc_identifier(
            "208.9% of Shareholder's Equity - Investments made in Ireland "
            "- Hotel, Gaming & Leisure - Flutter Entertainment plc "
            "- First Lien - Term Loan"
        )
        assert issuer == "Flutter Entertainment plc"

    def test_blue_owl_geography_no_industry(self):
        """Blue Owl geography prefix where seg[3] is company, not industry."""
        issuer, instrument = _parse_bdc_identifier(
            "150.0% of Shareholder's Equity - Investments made in USA "
            "- Acme Corp - Senior Secured Term Loan"
        )
        assert issuer == "Acme Corp"

    def test_saratoga_pct_only_prefix_with_issuer(self):
        """Saratoga: pct-only first segment, then issuer, industry, instrument."""
        issuer, instrument = _parse_bdc_identifier(
            "10.2% - Pepper Palace, Inc. - Specialty Food Retailer "
            "- First Lien Term Loan"
        )
        assert issuer == "Pepper Palace, Inc."
        assert instrument == "Specialty Food Retailer - First Lien Term Loan"

    def test_saratoga_pct_only_prefix_with_tight_dash_spacing(self):
        """Saratoga sometimes omits the space after an issuer/industry dash."""
        issuer, instrument = _parse_bdc_identifier(
            "220.9% - JDXpert -Talent Acquisition Software - "
            "First Lien Term Loan (3M USD TERM SOFR+8.50%)"
        )
        assert issuer == "JDXpert"
        assert instrument.startswith("Talent Acquisition Software - First Lien Term Loan")

    def test_saratoga_pct_only_prefix_category_row_stays_ambiguous(self):
        """Three-segment pct/category/instrument rows do not expose an issuer."""
        issuer, instrument = _parse_bdc_identifier(
            "10.6% - Education Services - Common Stock"
        )
        assert issuer == "10.6%"
        assert instrument == "Education Services - Common Stock"

    def test_entity_signal_in_seg1_preserves_default(self):
        """Seg[1] with entity signal (LLC) should NOT trigger pct-prefix skip."""
        issuer, instrument = _parse_bdc_identifier(
            "150% Acme Holdings, LLC - Senior Loan"
        )
        assert issuer == "150% Acme Holdings, LLC"
        assert instrument == "Senior Loan"

    def test_normal_identifier_unaffected(self):
        """Normal identifiers without pct prefix are unchanged."""
        issuer, instrument = _parse_bdc_identifier(
            "Acme Corp - First Lien Term Loan"
        )
        assert issuer == "Acme Corp"
        assert instrument == "First Lien Term Loan"

    def test_pennantpark_keyword_boundary_maturity(self):
        """Keyword boundary stops at 'Maturity'."""
        issuer, instrument = _parse_bdc_identifier(
            "184.3% First Lien Secured Debt - 112.9% "
            "GlobalTech Solutions, Inc. Maturity 12/15/2028"
        )
        assert issuer == "GlobalTech Solutions, Inc."

    def test_pennantpark_keyword_boundary_interest_rate(self):
        """Keyword boundary stops at 'Interest Rate'."""
        issuer, instrument = _parse_bdc_identifier(
            "160.0% First Lien Secured Debt - 80.5% "
            "FooBar Holdings LLC Interest Rate 10.50%"
        )
        assert issuer == "FooBar Holdings LLC"

    def test_no_dash_issuer_name_with_pct_prefix(self):
        """No-dash format with pct prefix before category text."""
        issuer, instrument = _parse_bdc_identifier(
            "177.4% Common Equity/Partnership Interests/Warrants "
            "Issuer Name Widget Co., Inc. Industry Technology"
        )
        assert issuer == "Widget Co., Inc."
        assert "Common Equity/Partnership Interests/Warrants" in instrument


class TestPctPrefixSqlPath:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """Integration tests verifying pct-prefix parsing through the SQL path."""

    def _run_prepare_bdc(
        self,
        identifier,
        fair_value=1000000.0,
        cik="0001504619",
        entity_name="PennantPark",
        report_date="2024-01-31",
    ):
        """Helper: run a single identifier through _prepare_bdc."""
        df = pd.DataFrame([{
            "cik": cik,
            "entity_name": entity_name,
            "accession_number": f"{cik}-24-000001",
            "form_type": "10-K",
            "filing_date": "2024-03-15",
            "report_date": report_date,
            "period": report_date,
            "investment_identifier": identifier,
            "fair_value": fair_value,
            "cost": fair_value,
            "principal_amount": None,
            "interest_rate": None,
            "basis_spread": None,
            "reference_rate_type": None,
            "maturity_date": None,
            "shares_held": None,
            "pct_of_net_assets": None,
            "unrealized_gain_loss": None,
            "pik_rate": None,
            "industry": None,
            "investment_type": None,
            "affiliation": None,
            "dimensions_raw": None,
        }])
        result = _prepare_bdc(df)
        return result

    def test_pennantpark_dash_sql(self):
        """SQL path produces correct issuer_name for PennantPark dash format."""
        result = self._run_prepare_bdc(
            "184.3% First Lien Secured Debt - 112.9% Issuer Name "
            "Seaway Buyer, LLC Maturity 06/13/2029 Industry Chemicals"
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Seaway Buyer, LLC"

    def test_pennantpark_emdash_sql(self):
        """SQL path normalises em-dash and extracts correct issuer."""
        result = self._run_prepare_bdc(
            "177.4% Common Equity/Partnership Interests/Warrants"
            "\u2014"
            "23.0% SP L2 Holdings, LLC Industry Consumer Products"
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "SP L2 Holdings, LLC"

    def test_blue_owl_geography_sql(self):
        """SQL path handles Blue Owl geography prefix."""
        result = self._run_prepare_bdc(
            "208.9% of Shareholder's Equity - Investments made in Ireland "
            "- Hotel, Gaming & Leisure - Flutter Entertainment plc "
            "- First Lien - Term Loan"
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Flutter Entertainment plc"

    def test_saratoga_pct_only_after_affiliation_strip_sql(self):
        """SQL path strips affiliation and recovers issuer after pct-only segment."""
        result = self._run_prepare_bdc(
            "Non-control/Non-affiliate investments - 229.3% - Avantra - "
            "IT Services - First Lien Term Loan (3M USD TERM SOFR+7.97%), "
            "12.29% Cash, 9/20/2029"
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Avantra"
        assert result.iloc[0]["instrument_description"].startswith(
            "IT Services - First Lien Term Loan"
        )

    def test_saratoga_tight_dash_spacing_sql(self):
        """SQL path normalizes missing space after dash in Saratoga identifiers."""
        result = self._run_prepare_bdc(
            "Non-control/Non-affiliate investments - 220.9% - JDXpert "
            "-Talent Acquisition Software - First Lien Term Loan "
            "(3M USD TERM SOFR+8.50%), 13.09% Cash, 5/2/2027"
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "JDXpert"
        assert result.iloc[0]["instrument_description"].startswith(
            "Talent Acquisition Software - First Lien Term Loan"
        )

    def test_saratoga_pct_only_category_row_filtered_sql(self):
        """Ambiguous pct/category/instrument rows are not promoted to positions."""
        result = self._run_prepare_bdc(
            "Control investments - 10.6% - Education Services - Common Stock"
        )
        assert result.empty

    def test_saratoga_exact_bridge_promotes_known_issuerless_leaf_sql(self):
        """Reviewed Saratoga CIK-period signatures recover the missing issuer."""
        result = self._run_prepare_bdc(
            "Non-control/Non-affiliate investments - 229.3% - "
            "Direct Selling Software - Common Units",
            cik="0001377936",
            entity_name="Saratoga Investment Corp.",
            report_date="2025-02-28",
            fair_value=729464,
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Exigo, LLC"
        assert (
            result.iloc[0]["instrument_description"]
            == "Direct Selling Software - Common Units"
        )

    def test_saratoga_bridge_is_period_exact_sql(self):
        """The Saratoga bridge does not globally promote category rows."""
        result = self._run_prepare_bdc(
            "Control investments - 10.6% - Education Services - Common Stock",
            cik="0001377936",
            entity_name="Saratoga Investment Corp.",
            report_date="2025-09-30",
        )
        assert result.empty

    def test_entity_signal_preserves_default_sql(self):
        """Entity signal in seg[1] prevents pct-prefix skip in SQL path."""
        result = self._run_prepare_bdc(
            "150% Acme Holdings, LLC - Senior Loan"
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "150% Acme Holdings, LLC"

    def test_normal_identifier_sql(self):
        """Normal identifiers unchanged through SQL path."""
        result = self._run_prepare_bdc(
            "Acme Corp - First Lien Term Loan"
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_sixth_street_no_dash_hierarchy_sql(self):
        """Sixth Street no-dash hierarchy rows expose issuer and tranche terms."""
        result = self._run_prepare_bdc(
            "Debt Investments Business Services OutSystems Luxco SARL "
            "First-lien loan (EUR 3,263 par, due 12/2028) Initial Acquisition Date "
            "12/8/2022 Reference Rate and Spread E + 5.75% Interest Rate 8.74%",
            cik="0001508655",
            entity_name="Sixth Street Specialty Lending, Inc.",
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "OutSystems Luxco SARL"
        assert result.iloc[0]["instrument_description"].startswith("First-lien loan")

    def test_fidelity_no_dash_hierarchy_sql(self):
        """Fidelity hierarchy rows should not be lost as aggregate headers."""
        result = self._run_prepare_bdc(
            "Investments Investments - non-controlled / non-affiliate First Lien Debt "
            "Advertising MMGY Global LLC Revolving Credit Facility Maturity Date 4/25/2029",
            cik="0001920453",
            entity_name="Fidelity Private Credit Fund",
        )
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "MMGY Global LLC"
        assert result.iloc[0]["instrument_description"].startswith(
            "Revolving Credit Facility"
        )


class TestGSPrivateCreditSqlPath:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """GS Private Credit (0001920145) Reference Rate / bare Maturity rescue."""

    def _run_prepare_bdc(
        self,
        identifier,
        fair_value=1000000.0,
        cik="0001920145",
        entity_name="Goldman Sachs Private Credit Corp.",
    ):
        df = pd.DataFrame([{
            "cik": cik,
            "entity_name": entity_name,
            "accession_number": f"{cik}-24-000001",
            "form_type": "10-K",
            "filing_date": "2024-03-15",
            "report_date": "2024-03-31",
            "period": "2024-03-31",
            "investment_identifier": identifier,
            "fair_value": fair_value,
            "cost": fair_value,
            "principal_amount": None,
            "interest_rate": None,
            "basis_spread": None,
            "reference_rate_type": None,
            "maturity_date": None,
            "shares_held": None,
            "pct_of_net_assets": None,
            "unrealized_gain_loss": None,
            "pik_rate": None,
            "industry": None,
            "investment_type": None,
            "affiliation": None,
            "dimensions_raw": None,
        }])
        from pipeline.staging_bdc import _prepare_bdc
        return _prepare_bdc(df)

    def test_gs_reference_rate_leaf_survives_aggregate_filter(self):
        """GS positions with Reference Rate (no Interest Rate) must not be
        filtered as aggregates.  These are BSL positions where GS omits the
        explicit Interest Rate field."""
        result = self._run_prepare_bdc(
            "Investment 1st Lien/Senior Secured Debt - 93.10% United States "
            "- 3.1% Acrisure, LLC Insurance Reference Rate and Spread "
            "S + 4.25% Maturity 02/15/2029"
        )
        assert len(result) == 1, "Reference Rate leaf dropped by aggregate filter"

    def test_gs_interest_rate_leaf_survives(self):
        """GS positions with explicit Interest Rate field survive (baseline)."""
        result = self._run_prepare_bdc(
            "Investment 1st Lien/Senior Secured Debt - 93.10% United States "
            "- 85.3% Acme Corp Industry Software Interest Rate 11.58% "
            "Reference Rate and Spread S + 5.75% Maturity 01/15/2028"
        )
        assert len(result) == 1

    def test_gs_aggregate_row_still_filtered(self):
        """Geographic subtotal row should still be filtered as aggregate."""
        result = self._run_prepare_bdc(
            "Investment United States - 104.84%",
            fair_value=500000000.0,
        )
        assert result.empty, "Geographic subtotal should be filtered"

    # --- Hierarchical pct identifier parser tests ---

    def test_gs_4seg_debt_issuer_name(self):
        """4-seg debt: issuer_name = company from leaf segment."""
        result = self._run_prepare_bdc(
            "Investment Debt Investments - 180.7% United Kingdom "
            "- 4.7% 1st Lien/Senior Secured Debt "
            "- 4.4% Polaris Newco, LLC Industry IT Services Interest Rate "
            "9.58% Reference Rate and Spread S + 5.50% Maturity 06/02/2028"
        )
        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Polaris Newco, LLC"

    def test_gs_4seg_debt_instrument_description(self):
        """4-seg debt: instrument_description = lien type from seg[-2]."""
        result = self._run_prepare_bdc(
            "Investment Debt Investments - 180.7% United Kingdom "
            "- 4.7% 1st Lien/Senior Secured Debt "
            "- 4.4% Polaris Newco, LLC Industry IT Services Interest Rate "
            "9.58% Reference Rate and Spread S + 5.50% Maturity 06/02/2028"
        )
        assert len(result) == 1
        assert result.iloc[0]["instrument_description"] == "1st Lien/Senior Secured Debt"

    def test_gs_4seg_debt_country(self):
        """4-seg debt: country extracted from seg[2]."""
        result = self._run_prepare_bdc(
            "Investment Debt Investments - 180.7% United Kingdom "
            "- 4.7% 1st Lien/Senior Secured Debt "
            "- 4.4% Polaris Newco, LLC Industry IT Services Interest Rate "
            "9.58% Reference Rate and Spread S + 5.50% Maturity 06/02/2028"
        )
        assert len(result) == 1
        assert result.iloc[0]["bdc_investment_country"] == "United Kingdom"

    def test_gs_4seg_debt_industry(self):
        """4-seg debt: extracted_industry from leaf after 'Industry' keyword."""
        result = self._run_prepare_bdc(
            "Investment Debt Investments - 180.7% United Kingdom "
            "- 4.7% 1st Lien/Senior Secured Debt "
            "- 4.4% Polaris Newco, LLC Industry IT Services Interest Rate "
            "9.58% Reference Rate and Spread S + 5.50% Maturity 06/02/2028"
        )
        assert len(result) == 1
        assert result.iloc[0]["extracted_industry"] == "IT Services"

    def test_gs_4seg_debt_reference_rate(self):
        """4-seg debt: reference_rate_type from S + shorthand."""
        result = self._run_prepare_bdc(
            "Investment Debt Investments - 180.7% United Kingdom "
            "- 4.7% 1st Lien/Senior Secured Debt "
            "- 4.4% Polaris Newco, LLC Industry IT Services Interest Rate "
            "9.58% Reference Rate and Spread S + 5.50% Maturity 06/02/2028"
        )
        assert len(result) == 1
        assert result.iloc[0]["reference_rate_type"] == "SOFR"

    def test_gs_3seg_debt_country_and_issuer(self):
        """3-seg debt: country from seg[2], issuer from leaf."""
        result = self._run_prepare_bdc(
            "Investment 1st Lien/Senior Secured Debt - 93.10% United States "
            "- 85.3% Acme Corp Industry Software Interest Rate 11.58% "
            "Reference Rate and Spread S + 5.75% Maturity 01/15/2028"
        )
        assert len(result) == 1
        row = result.iloc[0]
        assert row["bdc_investment_country"] == "United States"
        assert row["issuer_name"] == "Acme Corp"

    def test_gs_3seg_debt_instrument(self):
        """3-seg debt: instrument = seg[1] minus 'Investment ' = lien type."""
        result = self._run_prepare_bdc(
            "Investment 1st Lien/Senior Secured Debt - 93.10% United States "
            "- 85.3% Acme Corp Industry Software Interest Rate 11.58% "
            "Reference Rate and Spread S + 5.75% Maturity 01/15/2028"
        )
        assert len(result) == 1
        assert result.iloc[0]["instrument_description"] == "1st Lien/Senior Secured Debt"

    def test_gs_4seg_equity_issuer(self):
        """4-seg equity: issuer_name = company, not 'Equity and Other'."""
        result = self._run_prepare_bdc(
            "Equity and Other - 0.7% United States "
            "- 0.1% Preferred Stock "
            "- 0.0% SDB HOLDCO, LLC Aerospace & Defense"
        )
        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "SDB HOLDCO, LLC"

    def test_gs_4seg_equity_instrument(self):
        """4-seg equity: instrument = subcategory from seg[-2]."""
        result = self._run_prepare_bdc(
            "Equity and Other - 0.7% United States "
            "- 0.1% Preferred Stock "
            "- 0.0% SDB HOLDCO, LLC Aerospace & Defense"
        )
        assert len(result) == 1
        assert result.iloc[0]["instrument_description"] == "Preferred Stock"

    def test_gs_4seg_equity_country(self):
        """4-seg equity: country from seg[2]."""
        result = self._run_prepare_bdc(
            "Equity and Other - 0.7% United States "
            "- 0.1% Preferred Stock "
            "- 0.0% SDB HOLDCO, LLC Aerospace & Defense"
        )
        assert len(result) == 1
        assert result.iloc[0]["bdc_investment_country"] == "United States"

    def test_gs_4seg_equity_trailing_industry(self):
        """4-seg equity: extracted_industry from trailing label match."""
        result = self._run_prepare_bdc(
            "Equity and Other - 0.7% United States "
            "- 0.1% Preferred Stock "
            "- 0.0% SDB HOLDCO, LLC Aerospace & Defense"
        )
        assert len(result) == 1
        # "Aerospace & Defense" is a known industry label
        assert result.iloc[0]["extracted_industry"] == "Aerospace & Defense"

    def test_gs_equity_no_trailing_industry(self):
        """4-seg equity without trailing industry label: issuer absorbs
        terminal text, industry stays empty."""
        result = self._run_prepare_bdc(
            "Equity and Other - 0.7% United States "
            "- 0.1% Common Stock "
            "- 0.0% Unusual Holdings Corp"
        )
        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Unusual Holdings Corp"
        assert row["extracted_industry"] == ""

    def test_gs_comma_delimited_hierarchical_pct_equity(self):
        """Comma-delimited GS hierarchy still parses the percent-prefixed leaf."""
        result = self._run_prepare_bdc(
            "Equity Securities - 4.51%, United States - 4.51%, "
            "Common Stock - 1.06%, Foundation Software - Class B, "
            "Construction & Engineering, Initial Acquisition Date 08/31/20",
            cik="0001772704",
            entity_name="Goldman Sachs Private Middle Market Credit II LLC",
        )
        assert len(result) == 1
        row = result.iloc[0]
        assert "Foundation Software" in row["issuer_name"]
        assert row["instrument_description"] == "Common Stock"
        assert row["bdc_investment_country"] == "United States"

    def test_gs_comma_delimited_hierarchical_pct_equity_without_issuer_dash(self):
        """Comma-delimited GS hierarchy keeps the instrument category segment."""
        result = self._run_prepare_bdc(
            "Equity Securities - 4.51%, United States - 4.51%, "
            "Preferred Stock - 3.43%, CloudBees, Inc., Software, "
            "Initial Acquisition Date 11/24/21",
            cik="0001772704",
            entity_name="Goldman Sachs Private Middle Market Credit II LLC",
        )
        assert len(result) == 1
        row = result.iloc[0]
        assert "CloudBees" in row["issuer_name"]
        assert row["instrument_description"] == "Preferred Stock"
        assert row["bdc_investment_country"] == "United States"

    def test_gs_middle_market_no_dash_hierarchy_debt(self):
        """CIK 0001674760 no-dash hierarchy extracts issuer and instrument."""
        result = self._run_prepare_bdc(
            "Debt Investments United States 1st Lien/Senior Secured Debt "
            "Xactly Corporation IT Services Interest Rate 12.70% Reference Rate "
            "and Spread S + 7.25% Maturity 07/31/25",
            cik="0001674760",
            entity_name="Goldman Sachs Private Middle Market Credit LLC",
        )

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Xactly Corporation"
        assert row["instrument_description"] == "1st Lien/Senior Secured Debt"
        assert row["reference_rate_type"] == "SOFR"

    def test_gs_middle_market_no_country_hierarchy_debt(self):
        """CIK 0001674760 debt rows can omit the country bucket."""
        result = self._run_prepare_bdc(
            "1st Lien/Last-Out Unitranche Doxim, Inc. Diversified Financial "
            "Services Interest Rate 11.24% Reference Rate and Spread S + 6.40% "
            "Maturity 08/31/24",
            cik="0001674760",
            entity_name="Goldman Sachs Private Middle Market Credit LLC",
        )

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Doxim, Inc."
        assert row["instrument_description"] == "1st Lien/Last-Out Unitranche"
        assert row["reference_rate_type"] == "SOFR"

    def test_gs_middle_market_bare_affiliate_filtered_from_sql_path(self):
        """Bare affiliate subtotal is not kept as a position-level holding."""
        result = self._run_prepare_bdc(
            "Non-Controlled Affiliated Investments Collaborative Imaging, LLC "
            "(dba Texas Radiology Associates)",
            fair_value=2600000.0,
            cik="0001674760",
            entity_name="Goldman Sachs Private Middle Market Credit LLC",
        )

        assert result.empty

    def test_non_gs_cik_unaffected(self):
        """Non-GS CIK: hierarchical pct parser must NOT fire."""
        df = pd.DataFrame([{
            "cik": "0001418076",
            "entity_name": "Saratoga Investment Corp.",
            "accession_number": "0001418076-24-000001",
            "form_type": "10-K",
            "filing_date": "2024-03-15",
            "report_date": "2024-03-31",
            "period": "2024-03-31",
            "investment_identifier": "Acme Corp, LLC - Term Loan - First Lien",
            "fair_value": 1000000.0,
            "cost": 1000000.0,
            "principal_amount": None,
            "interest_rate": 10.0,
            "basis_spread": 5.0,
            "reference_rate_type": "SOFR",
            "maturity_date": "2028-01-15",
            "shares_held": None,
            "pct_of_net_assets": None,
            "unrealized_gain_loss": None,
            "pik_rate": None,
            "industry": None,
            "investment_type": None,
            "affiliation": None,
            "dimensions_raw": None,
        }])
        from pipeline.staging_bdc import _prepare_bdc
        result = _prepare_bdc(df)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Acme Corp, LLC"
        # Non-GS: bdc_investment_country stays empty
        assert row["bdc_investment_country"] == ""


class TestCrescentHierarchySqlPath:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """Crescent-family identifiers should parse as real leaf positions."""

    def _run_prepare_bdc(self, rows):
        cols = [
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "period", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "shares_held", "pct_of_net_assets", "unrealized_gain_loss",
            "pik_rate", "industry", "investment_type", "affiliation",
            "dimensions_raw",
        ]
        data = []
        for i, row in enumerate(rows):
            full_row = {c: "" for c in cols}
            full_row.update({
                "cik": "0001633336",
                "entity_name": "Crescent Capital BDC",
                "accession_number": "0001633336-24-000001",
                "form_type": "10-K",
                "filing_date": "2024-03-01",
                "report_date": "2023-12-31",
                "period": "2023-12-31",
                "fair_value": 1000000 + i,
                "cost": 1000000 + i,
            })
            full_row.update(row)
            data.append(full_row)
        return _prepare_bdc(pd.DataFrame(data))

    def test_crescent_capital_legal_suffix_row(self):
        result = self._run_prepare_bdc([{
            "investment_identifier": (
                "Investments Australia Debt Investments Retailing "
                "Greencross (Vermont Aus Pty Ltd) Investment\u00a0Type "
                "Unitranche First Lien Term Loan Interest Term\u00a0B + 575 "
                "Interest Rate 9.52% Maturity/ Dissolution Date 03/2028"
            )
        }])

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Greencross (Vermont Aus Pty Ltd)"
        assert row["instrument_description"] == "Unitranche First Lien Term Loan"
        assert row["maturity_date"] == "2028-03-31"

    def test_crescent_capital_equity_leaf_without_country_prefix(self):
        result = self._run_prepare_bdc([{
            "investment_identifier": (
                "Equity Investments Consumer Services Legalshield "
                "Investment Type Common Stock"
            ),
            "shares_held": 100,
        }])

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Legalshield"
        assert row["instrument_description"] == "Common Stock"

    def test_crescent_capital_equity_leaf_without_investment_type(self):
        result = self._run_prepare_bdc([{
            "investment_identifier": (
                "Equity Investments Health Care Equipment & Services "
                "Patriot Acquisition Topco S.A.R.L Common Stock One"
            ),
            "shares_held": 100,
        }])

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Patriot Acquisition Topco S.A.R.L"
        assert row["instrument_description"] == "Common Stock One"

    def test_crescent_capital_legacy_diversified_partnership_interest(self):
        result = self._run_prepare_bdc([{
            "investment_identifier": (
                "Equity Investments Diversified GACP II LP "
                "Investment Type Partnership Interest"
            ),
            "shares_held": 100,
        }])

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "GACP II LP"
        assert row["instrument_description"] == "Partnership Interest"

    def test_crescent_capital_investment_one_type_debt_leaf(self):
        result = self._run_prepare_bdc([{
            "investment_identifier": (
                "Investments United Kingdom Debt Investments Commercial & "
                "Professional Services Nurture Landscapes Investment One Type "
                "Unitranche First Lien Delayed Draw Term Loan Interest Term "
                "SN + 650 Interest Rate 10.96% Maturity/ Dissolution Date 06/2028"
            ),
            "principal_amount": 1000000,
            "interest_rate": 0.1096,
            "maturity_date": "2028-06-30",
        }])

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Nurture Landscapes"
        assert row["instrument_description"] == "Unitranche First Lien Delayed Draw Term Loan"

    def test_crescent_private_credit_no_legal_suffix_row(self):
        result = self._run_prepare_bdc([{
            "cik": "0001954360",
            "entity_name": "Crescent Private Credit Income Corp.",
            "accession_number": "0001954360-24-000001",
            "investment_identifier": (
                "Investments United States Debt Investments Software & Services "
                "Playgreen Investment Type Unitranche First Lien Term Loan "
                "Interest Term S + 625 Interest Rate 11.91% "
                "Maturity/Dissolution Date 04/2031"
            ),
        }])

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Playgreen"
        assert row["instrument_description"] == "Unitranche First Lien Term Loan"
        assert row["maturity_date"] == "2031-04-30"

    def test_multi_tranche_borrower_rows_remain_distinct_positions(self):
        base = (
            "Investments Canada Debt Investments Health Care Equipment & Services "
            "VetStrategy Investment Type Unitranche First Lien Delayed Draw "
            "Term Loan Interest Term C + 700 (100 Floor) Interest Rate 11.95% "
            "Maturity/ Dissolution Date 07/2027"
        )
        result = self._run_prepare_bdc([
            {"investment_identifier": f"{base} One", "fair_value": 1252000, "cost": 1252000},
            {"investment_identifier": f"{base} Two", "fair_value": 1252000, "cost": 1252000},
            {"investment_identifier": f"{base} Five", "fair_value": 4375000, "cost": 4375000},
        ])

        rows = result[result["issuer_name"] == "VetStrategy"]
        assert len(rows) == 3
        assert set(rows["instrument_description"]) == {
            "Unitranche First Lien Delayed Draw Term Loan - One",
            "Unitranche First Lien Delayed Draw Term Loan - Two",
            "Unitranche First Lien Delayed Draw Term Loan - Five",
        }

    def test_crescent_style_header_without_investment_type_filtered(self):
        result = self._run_prepare_bdc([{
            "investment_identifier": "Investments Canada Debt Investments",
            "fair_value": 5000000,
            "cost": 5000000,
        }])
        assert result.empty

    def test_crescent_style_equity_header_without_leaf_instrument_filtered(self):
        result = self._run_prepare_bdc([{
            "investment_identifier": "Equity Investments Consumer Services",
            "fair_value": 5000000,
            "cost": 5000000,
        }])
        assert result.empty


# ---------------------------------------------------------------------------
# Rate boundary fix: exactly 50 treated as bps (#6)
# ---------------------------------------------------------------------------

class TestRateBoundary50SqlPath:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """Rate=50 is implausible as percentage; treated as bps /100 = 0.50."""

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

    def test_interest_rate_50_normalized(self):
        """interest_rate=50 -> 0.50% (bps band)."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan",
            "cik": "123", "fair_value": 1000000, "interest_rate": 50,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["interest_rate"] == pytest.approx(0.50)

    def test_basis_spread_50_normalized(self):
        """basis_spread=50 -> 0.50% (bps band)."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan",
            "cik": "123", "fair_value": 1000000,
            "interest_rate": 8.0, "basis_spread": 50,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["basis_spread"] == pytest.approx(0.50)

    def test_pik_rate_50_normalized(self):
        """pik_rate=50 -> 0.50% (bps band)."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan",
            "cik": "123", "fair_value": 1000000,
            "interest_rate": 8.0, "pik_rate": 50,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["pik_rate"] == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Maturity sentinel: year 2099 nullified (#11)
# ---------------------------------------------------------------------------

class TestMaturitySentinel2099:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """Maturity year 2099 (perpetual sentinel) is nullified."""

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

    def test_maturity_2099_nullified(self):
        """maturity_date with year 2099 is treated as empty."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Equity",
            "cik": "123", "fair_value": 1000000,
            "maturity_date": "2099-12-31",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == ""

    def test_maturity_2098_kept(self):
        """maturity_date with year 2098 is preserved (only 2099 is sentinel)."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan",
            "cik": "123", "fair_value": 1000000,
            "maturity_date": "2098-06-30",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == "2098-06-30"

    def test_maturity_normal_preserved(self):
        """Normal maturity date (2027) is preserved."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan",
            "cik": "123", "fair_value": 1000000,
            "maturity_date": "2027-03-15",
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["maturity_date"] == "2027-03-15"


# ---------------------------------------------------------------------------
# CUSIP placeholder nullification (#4)
# ---------------------------------------------------------------------------

class TestCusipPlaceholderNullification:
    pytestmark = SLOW_INTEGRATION_MARKS

    """Placeholder CUSIPs (999999999, 000000000) nullified in output."""

    def _make_nport_raw(self, rows):
        """Create raw N-PORT DataFrame (pre-staging format)."""
        cols = [
            "accession_number", "holding_id", "issuer_name", "issuer_lei",
            "issuer_title", "issuer_cusip", "balance", "unit",
            "other_unit_desc", "currency_code", "currency_value",
            "exchange_rate", "percentage", "payoff_profile", "asset_cat",
            "other_asset", "issuer_type", "other_issuer",
            "investment_country", "is_restricted_security",
            "fair_value_level", "derivative_cat", "maturity_date",
            "coupon_type", "annualized_rate", "is_default",
            "are_any_interest_payment", "is_any_portion_interest_paid",
            "identifier_isin", "identifier_ticker", "other_identifier",
            "cik", "registrant_name", "filing_date", "report_date",
            "sub_type", "series_name", "series_id", "quarter",
        ]
        data = []
        for row in rows:
            full_row = {c: "" for c in cols}
            full_row.update(row)
            data.append(full_row)
        return pd.DataFrame(data)

    def test_placeholder_999_nullified(self, tmp_path):
        """CUSIP '999999999' is nullified in unified output."""
        nport_df = self._make_nport_raw([{
            "cik": "1234567", "registrant_name": "Test Fund",
            "accession_number": "ACC1", "holding_id": "H1",
            "filing_date": "2024-04-15", "report_date": "2024-03-31",
            "issuer_name": "Acme Corp", "issuer_title": "Bond",
            "issuer_cusip": "999999999",
            "currency_value": "1000000", "percentage": "5.0",
            "asset_cat": "DBT", "issuer_type": "CORP",
            "payoff_profile": "Long", "investment_country": "US",
            "annualized_rate": "8.5", "coupon_type": "Fixed",
            "maturity_date": "2027-01-01", "balance": "1000000",
            "unit": "PA", "series_name": "S1", "series_id": "SID1",
            "quarter": "2024q1",
        }])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test_cusip.csv"):
            result = build_unified_holdings(
                bdc_df=pd.DataFrame(),
                nport_df=nport_df,
            )
        row = result[result["issuer_name"].str.contains("Acme", na=False)]
        assert len(row) >= 1
        cusip_val = row.iloc[0]["cusip"]
        # Placeholder CUSIP should be nullified (None, NaN, or empty)
        assert pd.isna(cusip_val) or str(cusip_val).strip() == ""

    def test_normal_cusip_preserved(self, tmp_path):
        """Normal CUSIP values are preserved."""
        nport_df = self._make_nport_raw([{
            "cik": "1234567", "registrant_name": "Test Fund",
            "accession_number": "ACC1", "holding_id": "H2",
            "filing_date": "2024-04-15", "report_date": "2024-03-31",
            "issuer_name": "Beta Corp", "issuer_title": "Bond",
            "issuer_cusip": "12345X789",
            "currency_value": "500000", "percentage": "2.5",
            "asset_cat": "DBT", "issuer_type": "CORP",
            "payoff_profile": "Long", "investment_country": "US",
            "annualized_rate": "7.0", "coupon_type": "Fixed",
            "maturity_date": "2028-06-15", "balance": "500000",
            "unit": "PA", "series_name": "S1", "series_id": "SID1",
            "quarter": "2024q1",
        }])
        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE",
                    tmp_path / "test_cusip.csv"):
            result = build_unified_holdings(
                bdc_df=pd.DataFrame(),
                nport_df=nport_df,
            )
        row = result[result["issuer_name"].str.contains("Beta", na=False)]
        assert len(row) >= 1
        assert row.iloc[0]["cusip"] == "12345X789"


# ---------------------------------------------------------------------------
# N-PORT maturity sentinel: year 2099 nullified (Finding A)
# ---------------------------------------------------------------------------

class TestNportMaturitySentinel2099:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """N-PORT maturity year 2099 (perpetual sentinel) is nullified."""

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

    def test_nport_maturity_2099_nullified(self):
        """maturity_date with year 2099 is treated as empty in N-PORT."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "maturity_date": "2099-12-31",
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["maturity_date"] == ""

    def test_nport_maturity_2098_kept(self):
        """maturity_date with year 2098 is preserved (only 2099 is sentinel)."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "maturity_date": "2098-06-30",
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["maturity_date"] == "2098-06-30"

    def test_nport_maturity_normal_preserved(self):
        """Normal maturity date is preserved in N-PORT."""
        df = self._make_nport_df([{
            "fair_value_level": "3", "cik": "100",
            "asset_cat": "LON", "issuer_type": "CORP",
            "maturity_date": "2027-03-15",
        }])
        result = _prepare_nport(df)
        assert result.iloc[0]["maturity_date"] == "2027-03-15"


# ---------------------------------------------------------------------------
# PIK rate post-normalization cap (Finding B)
# ---------------------------------------------------------------------------

class TestPikRatePostNormalization:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """PIK rates at boundary (raw 0.20-0.50) are fixed when they exceed
    the total interest rate after normalization."""

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

    def test_pik_0_5_with_rate_10_becomes_0_5(self):
        """Raw pik=0.5 (50 bps) with interest_rate=0.1025 (10.25%).
        After normalization: pik=50 > rate=10.25, so pik/100 = 0.50."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan (50 PIK)",
            "cik": "123", "fair_value": 1000000,
            "interest_rate": 0.1025, "pik_rate": 0.5,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["pik_rate"] == pytest.approx(0.50)
        assert result.iloc[0]["interest_rate"] == pytest.approx(10.25)

    def test_pik_0_25_with_rate_10_becomes_0_25(self):
        """Raw pik=0.25 (25 bps) with interest_rate=0.1086 (10.86%).
        After normalization: pik=25 > rate=10.86, so pik/100 = 0.25."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan (25 PIK)",
            "cik": "123", "fair_value": 1000000,
            "interest_rate": 0.1086, "pik_rate": 0.25,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["pik_rate"] == pytest.approx(0.25)

    def test_pik_100pct_loan_not_capped(self):
        """100% PIK loan: pik=0.1350 (13.5%) with rate=0.1350 (13.5%).
        After normalization: pik=13.5 == rate=13.5, no cap needed."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - PIK Loan",
            "cik": "123", "fair_value": 1000000,
            "interest_rate": 0.1350, "pik_rate": 0.1350,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["pik_rate"] == pytest.approx(13.50)
        assert result.iloc[0]["interest_rate"] == pytest.approx(13.50)

    def test_pik_below_20_not_capped(self):
        """PIK=15% with rate=10% is not capped (< 20 threshold)."""
        df = self._make_bdc_df([{
            "investment_identifier": "Acme Corp - Term Loan",
            "cik": "123", "fair_value": 1000000,
            "interest_rate": 0.10, "pik_rate": 0.15,
        }])
        result = _prepare_bdc(df)
        assert result.iloc[0]["pik_rate"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# TestLoadAggregateHeaderFlags
# ---------------------------------------------------------------------------

class TestLoadAggregateHeaderFlags:
    """Test loading and filtering of aggregate_header_flags.csv."""

    def test_returns_empty_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "pipeline.staging_bdc.AGGREGATE_HEADER_FLAGS_FILE",
            tmp_path / "nonexistent.csv",
        )
        result = _load_aggregate_header_flags()
        assert "name_norm" in result.columns
        assert "identifier_raw" in result.columns
        assert len(result) == 0

    def test_loads_only_aggregate_header_verdicts(self, monkeypatch, tmp_path):
        flags_path = tmp_path / "flags.csv"
        flags_df = pd.DataFrame([
            {"name_norm": "total debt investments", "verdict": "AGGREGATE_HEADER",
             "confidence": "high", "issuer_name_raw": "Total Debt Investments"},
            {"name_norm": "acme jv", "verdict": "JV_SUBSIDIARY",
             "confidence": "high", "issuer_name_raw": "Acme JV, LLC"},
            {"name_norm": "unknown thing", "verdict": "UNRESOLVABLE",
             "confidence": "medium", "issuer_name_raw": "Unknown Thing"},
        ])
        flags_df.to_csv(flags_path, index=False)
        monkeypatch.setattr(
            "pipeline.staging_bdc.AGGREGATE_HEADER_FLAGS_FILE",
            flags_path,
        )
        result = _load_aggregate_header_flags()
        assert len(result) == 1
        assert result.iloc[0]["name_norm"] == "total debt investments"

    def test_excludes_low_confidence_aggregate_headers(self, monkeypatch, tmp_path):
        flags_path = tmp_path / "flags.csv"
        flags_df = pd.DataFrame([
            {"name_norm": "maybe header", "verdict": "AGGREGATE_HEADER",
             "confidence": "low", "issuer_name_raw": "Maybe Header"},
            {"name_norm": "sure header", "verdict": "AGGREGATE_HEADER",
             "confidence": "high", "issuer_name_raw": "Sure Header"},
        ])
        flags_df.to_csv(flags_path, index=False)
        monkeypatch.setattr(
            "pipeline.staging_bdc.AGGREGATE_HEADER_FLAGS_FILE",
            flags_path,
        )
        result = _load_aggregate_header_flags()
        assert len(result) == 1
        assert result.iloc[0]["name_norm"] == "sure header"

    def test_handles_missing_columns_gracefully(self, monkeypatch, tmp_path):
        flags_path = tmp_path / "flags.csv"
        # File with wrong columns
        pd.DataFrame({"foo": ["bar"]}).to_csv(flags_path, index=False)
        monkeypatch.setattr(
            "pipeline.staging_bdc.AGGREGATE_HEADER_FLAGS_FILE",
            flags_path,
        )
        result = _load_aggregate_header_flags()
        assert len(result) == 0


class TestAggregateHeaderFlagExclusion:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """Test that CC-flagged aggregate headers are excluded in _prepare_bdc."""

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

    def test_flagged_aggregate_excluded(self, monkeypatch, tmp_path):
        """Rows matching an AGGREGATE_HEADER flag are excluded."""
        flags_path = tmp_path / "agg_flags.csv"
        # "total debt" is a name_norm that matches "Total Debt Holdings"
        # after SQL-side normalization (lower + strip legal suffixes)
        flags_df = pd.DataFrame([
            {"name_norm": "total debt", "verdict": "AGGREGATE_HEADER",
             "confidence": "high", "issuer_name_raw": "Total Debt"},
        ])
        flags_df.to_csv(flags_path, index=False)
        monkeypatch.setattr(
            "pipeline.staging_bdc.AGGREGATE_HEADER_FLAGS_FILE",
            flags_path,
        )

        df = self._make_bdc_df([
            {"investment_identifier": "Total Debt - Category Subtotal",
             "cik": "123", "fair_value": 50000000},
            {"investment_identifier": "Acme Corp - Term Loan",
             "cik": "123", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        # "Total Debt" should have been caught by the existing aggregate filter
        # or by the CC flag. "Acme Corp" should remain.
        names = result["issuer_name"].tolist()
        assert "Acme Corp" in names

    def test_jv_subsidiary_not_excluded(self, monkeypatch, tmp_path):
        """JV_SUBSIDIARY verdicts do NOT exclude rows."""
        flags_path = tmp_path / "agg_flags.csv"
        flags_df = pd.DataFrame([
            {"name_norm": "acme jv", "verdict": "JV_SUBSIDIARY",
             "confidence": "high", "issuer_name_raw": "Acme JV, LLC"},
        ])
        flags_df.to_csv(flags_path, index=False)
        monkeypatch.setattr(
            "pipeline.staging_bdc.AGGREGATE_HEADER_FLAGS_FILE",
            flags_path,
        )

        df = self._make_bdc_df([
            {"investment_identifier": "Acme JV, LLC - Equity",
             "cik": "123", "fair_value": 5000000},
            {"investment_identifier": "Beta Corp - Term Loan",
             "cik": "123", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        # JV_SUBSIDIARY should NOT be filtered - both rows should remain
        assert len(result) == 2

    def test_no_flags_file_no_exclusion(self, monkeypatch, tmp_path):
        """When no flags file exists, _prepare_bdc works normally."""
        monkeypatch.setattr(
            "pipeline.staging_bdc.AGGREGATE_HEADER_FLAGS_FILE",
            tmp_path / "nonexistent.csv",
        )

        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp - Term Loan",
             "cik": "123", "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"


class TestBdcAggregateOverrides:
    pytestmark = SLOW_STAGING_SQL_MARKS

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

    def _write_overrides(self, tmp_path, overrides):
        path = tmp_path / "bdc_aggregate_row_overrides.json"
        import json
        path.write_text(json.dumps({"overrides": overrides}), encoding="utf-8")
        return path

    def test_exact_exclude_preserves_detailed_same_issuer_position(self, monkeypatch, tmp_path):
        overrides_path = self._write_overrides(tmp_path, [{
            "cik": "0001287032",
            "report_date": "2024-03-31",
            "accession_number": "0001287032-24-000152",
            "match_text": "InterDent, Inc.",
            "match_mode": "exact",
            "action": "exclude",
            "reason": "test audited parent row",
            "evidence": "unit test",
            "review_id": "test",
            "updated_at": "2026-05-24",
        }])
        monkeypatch.setattr(
            "pipeline.bdc_aggregate_overrides.BDC_AGGREGATE_ROW_OVERRIDES_FILE",
            overrides_path,
        )

        df = self._make_bdc_df([
            {
                "cik": "1287032", "report_date": "2024-03-31",
                "accession_number": "0001287032-24-000152",
                "investment_identifier": "InterDent, Inc.",
                "fair_value": "5000000",
            },
            {
                "cik": "1287032", "report_date": "2024-03-31",
                "accession_number": "0001287032-24-000152",
                "investment_identifier": "InterDent, Inc. - First Lien Term Loan",
                "fair_value": "1000000",
            },
        ])
        result = _prepare_bdc(df)
        assert result["bdc_investment_identifier"].tolist() == [
            "InterDent, Inc. - First Lien Term Loan"
        ]

    def test_exact_match_mode_is_not_substring(self, monkeypatch, tmp_path):
        overrides_path = self._write_overrides(tmp_path, [{
            "cik": "0001287032",
            "match_text": "InterDent, Inc.",
            "match_mode": "exact",
            "action": "exclude",
            "reason": "test audited parent row",
            "evidence": "unit test",
            "review_id": "test",
            "updated_at": "2026-05-24",
        }])
        monkeypatch.setattr(
            "pipeline.bdc_aggregate_overrides.BDC_AGGREGATE_ROW_OVERRIDES_FILE",
            overrides_path,
        )

        df = self._make_bdc_df([{
            "cik": "1287032",
            "investment_identifier": "InterDent, Inc. - First Lien Term Loan",
            "fair_value": "1000000",
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "InterDent, Inc."

    def test_override_loader_prefers_primary_and_falls_back_to_legacy(self, monkeypatch, tmp_path):
        from pipeline.bdc_aggregate_overrides import (
            load_bdc_aggregate_overrides,
            resolve_bdc_aggregate_overrides_file,
        )

        primary = tmp_path / "data" / "overrides" / "bdc_aggregate_row_overrides.json"
        legacy = tmp_path / "data" / "output" / "bdc_aggregate_row_overrides.json"
        primary.parent.mkdir(parents=True)
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"overrides": [{
            "cik": "1",
            "match_text": "Legacy",
            "action": "exclude",
            "reason": "legacy fallback",
            "evidence": "unit test",
            "review_id": "legacy",
            "updated_at": "2026-05-27",
        }]}), encoding="utf-8")

        monkeypatch.setattr(
            "pipeline.bdc_aggregate_overrides.BDC_AGGREGATE_ROW_OVERRIDES_FILE",
            primary,
        )
        monkeypatch.setattr(
            "pipeline.bdc_aggregate_overrides.LEGACY_BDC_AGGREGATE_ROW_OVERRIDES_FILE",
            legacy,
        )
        assert resolve_bdc_aggregate_overrides_file() == legacy
        assert load_bdc_aggregate_overrides().iloc[0]["match_text"] == "Legacy"

        primary.write_text(json.dumps({"overrides": [{
            "cik": "1",
            "match_text": "Primary",
            "action": "exclude",
            "reason": "primary config",
            "evidence": "unit test",
            "review_id": "primary",
            "updated_at": "2026-05-27",
        }]}), encoding="utf-8")
        assert resolve_bdc_aggregate_overrides_file() == primary
        assert load_bdc_aggregate_overrides().iloc[0]["match_text"] == "Primary"

    def test_slr_equipment_financing_leaf_staged_from_seg2(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "pipeline.bdc_aggregate_overrides.BDC_AGGREGATE_ROW_OVERRIDES_FILE",
            tmp_path / "missing.json",
        )
        df = self._make_bdc_df([{
            "cik": "814585",
            "investment_identifier": (
                "Equipment Financing - 24.1% | Air Methods Corporation |Airlines| "
                "First Lien Term Loan | SOFR + 6.00% | 12/31/2028"
            ),
            "fair_value": "1000000",
        }])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Air Methods Corporation"

    def test_slr_total_pipe_row_excluded(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "pipeline.bdc_aggregate_overrides.BDC_AGGREGATE_ROW_OVERRIDES_FILE",
            tmp_path / "missing.json",
        )
        df = self._make_bdc_df([{
            "cik": "814585",
            "investment_identifier": "Equipment Financing - 24.1% | Total Equipment Financing",
            "fair_value": "1000000",
        }])
        result = _prepare_bdc(df)
        assert result.empty


class TestTextEnrichment:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """Integration tests for text-based field extraction from identifier text.

    Covers maturity 'due M/YYYY', interest rate, basis spread, PIK rate,
    and coupon type inference from identifier text when XBRL columns are NULL.
    """

    def _run_prepare_bdc(
        self,
        identifier,
        fair_value=1000000.0,
        cik="0001504619",
        entity_name="TestEntity",
        report_date="2024-01-31",
        interest_rate=None,
        basis_spread=None,
        pik_rate=None,
        reference_rate_type=None,
        maturity_date=None,
    ):
        """Helper: run a single identifier through _prepare_bdc."""
        df = pd.DataFrame([{
            "cik": cik,
            "entity_name": entity_name,
            "accession_number": f"{cik}-24-000001",
            "form_type": "10-K",
            "filing_date": "2024-03-15",
            "report_date": report_date,
            "period": report_date,
            "investment_identifier": identifier,
            "fair_value": fair_value,
            "cost": fair_value,
            "principal_amount": None,
            "interest_rate": interest_rate,
            "basis_spread": basis_spread,
            "reference_rate_type": reference_rate_type,
            "maturity_date": maturity_date,
            "shares_held": None,
            "pct_of_net_assets": None,
            "unrealized_gain_loss": None,
            "pik_rate": pik_rate,
            "industry": None,
            "investment_type": None,
            "affiliation": None,
            "dimensions_raw": None,
        }])
        result = _prepare_bdc(df)
        return result

    def test_sixth_street_due_maturity(self):
        """Sixth Street 'due M/YYYY' maturity is extracted."""
        result = self._run_prepare_bdc(
            "Debt Investments Business Services OutSystems Luxco SARL "
            "First-lien loan ($36,651 par, due 7/2030) Initial Acquisition Date "
            "12/8/2022 Reference Rate and Spread E + 5.75% Interest Rate 8.74%",
            cik="0001508655",
            entity_name="Sixth Street Specialty Lending, Inc.",
        )
        assert len(result) == 1
        assert result.iloc[0]["maturity_date"] == "2030-07-31"

    def test_trinity_fixed_rate(self):
        """Trinity 'Fixed interest rate 12.9%' text extraction."""
        result = self._run_prepare_bdc(
            "Acme Holdings, LLC - First Lien Term Loan - "
            "Fixed interest rate 12.9%; EOT 0.0%",
            cik="0001786108",
            entity_name="Trinity Capital Inc",
        )
        assert len(result) == 1
        assert result.iloc[0]["interest_rate"] == pytest.approx(12.9)
        assert result.iloc[0]["coupon_type"] == "Fixed"

    def test_trinity_variable_with_floor(self):
        """Trinity variable rate with floor and basis spread."""
        result = self._run_prepare_bdc(
            "Acme Holdings, LLC - First Lien Term Loan - Variable interest rate "
            "Prime + 6.0% or Floor rate 11.0%; EOT 3.0%",
            cik="0001786108",
            entity_name="Trinity Capital Inc",
        )
        assert len(result) == 1
        assert result.iloc[0]["interest_rate"] == pytest.approx(11.0)
        assert result.iloc[0]["basis_spread"] == pytest.approx(6.0)
        assert result.iloc[0]["reference_rate_type"] == "PRIME"
        assert result.iloc[0]["coupon_type"] == "Floating"

    def test_trinity_variable_with_pik(self):
        """Trinity floor rate + PIK Interest Rate are separated correctly."""
        result = self._run_prepare_bdc(
            "Acme Holdings, LLC - First Lien Term Loan - Floor rate 11.0%"
            "+PIK Interest Rate 1.0%; EOT 11.0%",
            cik="0001786108",
            entity_name="Trinity Capital Inc",
        )
        assert len(result) == 1
        assert result.iloc[0]["interest_rate"] == pytest.approx(11.0)
        assert result.iloc[0]["pik_rate"] == pytest.approx(1.0)

    def test_fidelity_compact_spread(self):
        """Fidelity compact 'SOFR+5.50% Interest Rate 10.70%' extraction."""
        result = self._run_prepare_bdc(
            "Investments First Lien Debt Acme LLC Term Loan "
            "SOFR+5.50% Interest Rate 10.70% Maturity Date 8/2/2030",
            cik="0001920453",
            entity_name="Fidelity Private Credit Fund",
        )
        assert len(result) == 1
        assert result.iloc[0]["basis_spread"] == pytest.approx(5.5)
        assert result.iloc[0]["interest_rate"] == pytest.approx(10.7)

    def test_saratoga_pik_rate(self):
        """Saratoga '15.00% PIK' text extraction."""
        result = self._run_prepare_bdc(
            "Non-control/Non-affiliate investments - 229.3% - "
            "Acme Holdings, LLC - First Lien Term Loan 15.00% PIK, 2/18/2028",
            cik="0001377936",
            entity_name="Saratoga Investment Corp.",
        )
        assert len(result) == 1
        assert result.iloc[0]["pik_rate"] == pytest.approx(15.0)

    def test_sixth_street_fully_pik(self):
        """Sixth Street fully-PIK position: IR = PIK rate."""
        result = self._run_prepare_bdc(
            "Debt Investments Business Services Acme LLC "
            "First-lien loan ($5,000 par, due 6/2029) "
            "Interest Rate 13.70% PIK",
            cik="0001508655",
            entity_name="Sixth Street Specialty Lending, Inc.",
        )
        assert len(result) == 1
        assert result.iloc[0]["interest_rate"] == pytest.approx(13.7)
        assert result.iloc[0]["pik_rate"] == pytest.approx(13.7)

    def test_xbrl_precedence(self):
        """XBRL structured values take precedence over text extraction."""
        result = self._run_prepare_bdc(
            "Acme Corp - First Lien Term Loan - Interest Rate 10.0%",
            interest_rate=8.5,
        )
        assert len(result) == 1
        assert result.iloc[0]["interest_rate"] == pytest.approx(8.5)

    def test_no_false_positives(self):
        """Plain identifier yields no text-derived fields."""
        result = self._run_prepare_bdc(
            "Acme Corp - First Lien Term Loan"
        )
        assert len(result) == 1
        row = result.iloc[0]
        assert row["interest_rate"] is None or pd.isna(row["interest_rate"])
        assert row["basis_spread"] is None or pd.isna(row["basis_spread"])
        assert row["pik_rate"] is None or pd.isna(row["pik_rate"])
        assert row["coupon_type"] == ""


# ---------------------------------------------------------------------------
# Wrapper non-private-market filtering in staging
# ---------------------------------------------------------------------------

class TestWrapperNonPrivateMarketFiltering:
    pytestmark = SLOW_STAGING_SQL_MARKS

    """Verify staging drops wrapper-tagged non-private-market rows."""

    # Use a real wrapper CIK so supported_wrapper_ciks() returns it
    _WRAPPER_CIK = "0001287750"
    _NON_WRAPPER_CIK = "0000999999"

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

    def test_wrapper_non_private_treasury_retained_as_cash(self):
        """U.S. Treasury row for a wrapper CIK is retained, marked asset_category=CASH.

        Cash equivalents are no longer dropped: they persist into the unified
        holdings as a Cash bucket (analytics-only) and are excluded from the
        position-level indices downstream by position matching.
        """
        df = self._make_bdc_df([
            {"investment_identifier": "U.S. Treasury Bill 2025-06-15",
             "cik": self._WRAPPER_CIK, "fair_value": 500000},
            {"investment_identifier": "Acme Corp - First Lien Term Loan",
             "cik": self._WRAPPER_CIK, "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        by_id = {r["bdc_investment_identifier"]: r for _, r in result.iterrows()}
        treasury = next(v for k, v in by_id.items() if "Treasury" in str(k))
        assert treasury["asset_category"] == "CASH"
        acme = next(v for k, v in by_id.items() if "Acme" in str(k))
        assert acme["asset_category"] in ("LOAN", "DEBT")

    def test_wrapper_non_private_does_not_affect_non_wrapper_cik(self):
        """Same treasury identifier for a non-wrapper CIK is NOT dropped."""
        df = self._make_bdc_df([
            {"investment_identifier": "U.S. Treasury Bill 2025-06-15",
             "cik": self._NON_WRAPPER_CIK, "fair_value": 500000},
            {"investment_identifier": "Acme Corp - First Lien Term Loan",
             "cik": self._NON_WRAPPER_CIK, "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        # Non-wrapper CIK: treasury row survives global keyword filter
        # (global keywords cover "money market" etc., not "u.s. treasury")
        assert len(result) == 2

    def test_wrapper_non_private_false_positive_guard(self):
        """Row with 'Cash + PIK Interest Rate 5%' is a loan, NOT a cash bucket.

        False-positive guard: a loan whose coupon mix mentions 'Cash + PIK'
        must survive as a debt position and must NOT be marked asset_category=CASH.
        """
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp - Senior Secured First Lien, Cash + PIK Interest Rate 5.00%",
             "cik": self._WRAPPER_CIK, "fair_value": 1000000,
             "interest_rate": 0.05},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert result.iloc[0]["asset_category"] != "CASH"

    def test_global_mm_keyword_retained_as_cash(self):
        """Row with 'Money Market' for any CIK is retained, marked asset_category=CASH."""
        df = self._make_bdc_df([
            {"investment_identifier": "Goldman Sachs Money Market Fund",
             "cik": self._NON_WRAPPER_CIK, "fair_value": 500000},
            {"investment_identifier": "Acme Corp - First Lien Term Loan",
             "cik": self._NON_WRAPPER_CIK, "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 2
        by_id = {r["bdc_investment_identifier"]: r for _, r in result.iterrows()}
        mm = next(v for k, v in by_id.items() if "Money Market" in str(k))
        assert mm["asset_category"] == "CASH"
        acme = next(v for k, v in by_id.items() if "Acme" in str(k))
        assert acme["asset_category"] in ("LOAN", "DEBT")


# ---------------------------------------------------------------------------
# Wrapper-authoritative staging: rescue/drop via wrapper disposition
# ---------------------------------------------------------------------------

class TestWrapperAuthoritativeStaging:
    """Verify that wrapper disposition overrides global aggregate/hierarchy
    heuristics in staging: *_position_leaf rescues, aggregate/*_rollup drops."""

    pytestmark = SLOW_STAGING_SQL_MARKS

    _FAKE_CIK = "0009999999"
    _MSD_CIK = "0001849894"
    _AUDAX_CIK = "0001633858"
    _BLACKROCK_PRIVATE_CREDIT_CIK = "0001902649"

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

    def test_wrapper_leaf_rescued_from_aggregate_filter(self, monkeypatch):
        """Row matching aggregate patterns is kept when wrapper says *_position_leaf."""
        import pipeline.staging_bdc as staging_mod

        def _fake_classify(cik, identifier):
            from pipeline.bdc_xbrl_wrapper import WRAPPER_COLUMNS
            result = {col: "" for col in WRAPPER_COLUMNS}
            if "Total Senior Secured Debt" in str(identifier):
                result["wrapper_disposition"] = "debt_position_leaf"
            return result

        monkeypatch.setattr(staging_mod, "supported_wrapper_ciks",
                            lambda: (self._FAKE_CIK,))
        monkeypatch.setattr(staging_mod, "classify_identifier", _fake_classify)

        df = self._make_bdc_df([
            # This identifier matches aggregate patterns ("Total ... Debt")
            # but wrapper says it's a leaf position
            {"investment_identifier": "Total Senior Secured Debt - Acme Corp First Lien Term Loan Interest Rate 8.00% Maturity 01/2028",
             "cik": self._FAKE_CIK, "fair_value": 1000000,
             "interest_rate": 0.08},
            # Normal position for baseline
            {"investment_identifier": "Beta LLC - Second Lien Term Loan",
             "cik": self._FAKE_CIK, "fair_value": 500000,
             "interest_rate": 0.06},
        ])
        result = _prepare_bdc(df)
        identifiers = result["bdc_investment_identifier"].tolist()
        # Both rows should survive: the "Total" row rescued by wrapper leaf
        assert len(result) == 2
        assert any("Total Senior Secured Debt" in str(i) for i in identifiers)

    def test_wrapper_rollup_not_dropped_by_staging(self, monkeypatch):
        """Wrapper rollup disposition does NOT drop rows in staging.

        Rollup/aggregate wrapper drop was intentionally omitted because some
        wrappers misclassify equity co-investments as debt_issuer_rollup
        (e.g., Fidelity).  The global agg_filter and per-CIK category_marker_re
        handle aggregate filtering instead.  Wrapper rollup rows that pass
        global rules are kept.
        """
        import pipeline.staging_bdc as staging_mod

        def _fake_classify(cik, identifier):
            from pipeline.bdc_xbrl_wrapper import WRAPPER_COLUMNS
            result = {col: "" for col in WRAPPER_COLUMNS}
            if "Acme LLC" in str(identifier):
                result["wrapper_disposition"] = "debt_issuer_rollup"
            return result

        monkeypatch.setattr(staging_mod, "supported_wrapper_ciks",
                            lambda: (self._FAKE_CIK,))
        monkeypatch.setattr(staging_mod, "classify_identifier", _fake_classify)

        df = self._make_bdc_df([
            # Wrapper says rollup but row has entity signals and FV
            # -> global rules keep it, wrapper rollup does not override
            {"investment_identifier": "Acme LLC - Equity Co-Investment",
             "cik": self._FAKE_CIK, "fair_value": 1000000},
            {"investment_identifier": "Beta Corp - First Lien Term Loan",
             "cik": self._FAKE_CIK, "fair_value": 500000,
             "interest_rate": 0.07},
        ])
        result = _prepare_bdc(df)
        # Both rows survive: wrapper rollup does not drop
        assert len(result) == 2

    def test_global_aggregate_filter_still_drops_rollup_text(self, monkeypatch):
        """Global agg_filter still drops rows matching aggregate patterns,
        regardless of wrapper disposition."""
        import pipeline.staging_bdc as staging_mod

        def _fake_classify(cik, identifier):
            from pipeline.bdc_xbrl_wrapper import WRAPPER_COLUMNS
            result = {col: "" for col in WRAPPER_COLUMNS}
            if "Total Investments" in str(identifier):
                result["wrapper_disposition"] = "debt_category_rollup"
            return result

        monkeypatch.setattr(staging_mod, "supported_wrapper_ciks",
                            lambda: (self._FAKE_CIK,))
        monkeypatch.setattr(staging_mod, "classify_identifier", _fake_classify)

        df = self._make_bdc_df([
            # Global agg_filter matches "Total ... Investments"
            {"investment_identifier": "Total Senior Secured First Lien Debt Investments",
             "cik": self._FAKE_CIK, "fair_value": 50000000},
            {"investment_identifier": "Gamma Inc. - Senior Secured First Lien Term Loan",
             "cik": self._FAKE_CIK, "fair_value": 1000000,
             "interest_rate": 0.09},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert "Gamma" in result.iloc[0]["issuer_name"]

    def test_wrapper_unclassified_uses_global_rules(self, monkeypatch):
        """Row matching aggregate patterns with unclassified disposition is dropped by global rules."""
        import pipeline.staging_bdc as staging_mod

        def _fake_classify(cik, identifier):
            from pipeline.bdc_xbrl_wrapper import WRAPPER_COLUMNS
            result = {col: "" for col in WRAPPER_COLUMNS}
            if "Total Investments" in str(identifier):
                result["wrapper_disposition"] = "debt_unclassified"
            return result

        monkeypatch.setattr(staging_mod, "supported_wrapper_ciks",
                            lambda: (self._FAKE_CIK,))
        monkeypatch.setattr(staging_mod, "classify_identifier", _fake_classify)

        df = self._make_bdc_df([
            # Global aggregate filter catches "Total Investments"
            # Wrapper returns unclassified -> global rules still apply -> dropped
            {"investment_identifier": "Total Investments",
             "cik": self._FAKE_CIK, "fair_value": 100000000},
            {"investment_identifier": "Delta Corp - Term Loan B",
             "cik": self._FAKE_CIK, "fair_value": 2000000,
             "interest_rate": 0.065},
        ])
        result = _prepare_bdc(df)
        assert len(result) == 1
        assert "Delta" in result.iloc[0]["issuer_name"]

    def test_wrapper_leaf_rescued_from_prefix_hierarchy(self, monkeypatch):
        """Row matching prefix_hierarchy filter is kept when wrapper says *_position_leaf."""
        import pipeline.staging_bdc as staging_mod

        def _fake_classify(cik, identifier):
            from pipeline.bdc_xbrl_wrapper import WRAPPER_COLUMNS
            result = {col: "" for col in WRAPPER_COLUMNS}
            if "Senior Secured First Lien" in str(identifier):
                result["wrapper_disposition"] = "debt_position_leaf"
            return result

        monkeypatch.setattr(staging_mod, "supported_wrapper_ciks",
                            lambda: (self._FAKE_CIK,))
        monkeypatch.setattr(staging_mod, "classify_identifier", _fake_classify)

        df = self._make_bdc_df([
            # This identifier might match prefix hierarchy patterns
            # but wrapper says it's a leaf position
            {"investment_identifier": "Senior Secured First Lien Debt Investments Epsilon Holdings Inc. Term Loan Interest Rate 7.50% Maturity 06/2027",
             "cik": self._FAKE_CIK, "fair_value": 3000000,
             "interest_rate": 0.075},
            {"investment_identifier": "Zeta Partners LLC - Revolving Credit Facility",
             "cik": self._FAKE_CIK, "fair_value": 1500000,
             "interest_rate": 0.055},
        ])
        result = _prepare_bdc(df)
        identifiers = result["bdc_investment_identifier"].tolist()
        # Both should survive: the prefix-hierarchy row rescued by wrapper leaf
        assert len(result) == 2
        assert any("Senior Secured First Lien" in str(i) for i in identifiers)

    def test_msd_category_rollup_is_dropped_but_leaf_is_kept(self):
        """MSD category FV rows are dropped while real child positions survive."""
        category = (
            "Investments Investments - non-controlled/non-affiliated "
            "First Lien Debt Services: Consumer"
        )
        leaf = (
            "Investments Investments - non-controlled/non-affiliated "
            "First Lien Debt Services: Consumer PetVet Care Centers "
            "Reference Rate and Spread S + 6.00% Interest Rate Floor 0.75% "
            "Interest Rate 11.34% Maturity Date 11/15/2030"
        )
        df = self._make_bdc_df([
            {
                "investment_identifier": category,
                "cik": self._MSD_CIK,
                "fair_value": 328916000,
                "cost": 328744000,
            },
            {
                "investment_identifier": leaf,
                "cik": self._MSD_CIK,
                "fair_value": 53122000,
                "cost": 52257000,
                "principal_amount": 53255000,
                "interest_rate": 0.1134,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "PetVet Care Centers"
        assert "Reference Rate and Spread" in row["instrument_description"]
        assert float(row["fair_value"]) == 53122000

    def test_blackrock_private_credit_no_marker_leaf_extracts_issuer(self):
        """BlackRock Private Credit no-marker loan rows parse issuer/instrument."""
        raw = (
            "Debt Investments IT Services Avalara, Inc. First Lien Term Loan "
            "Ref SOFR(Q) Floor 0.75% Spread 7.25% Total Coupon 12.64%"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": self._BLACKROCK_PRIVATE_CREDIT_CIK,
            "fair_value": 974928,
            "cost": 968602,
            "principal_amount": 1000000,
            "interest_rate": 0.1264,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Avalara, Inc."
        assert row["instrument_description"] == "First Lien Term Loan"

    def test_blackrock_private_credit_borrowerless_leaf_remains_review_item(self):
        """Rows with loan terms but no borrower are not assigned fake issuers."""
        raw = (
            "Debt Investments Household Durables First Lien Term Loan B Ref "
            "SOFR(Q) Floor 1.00% Spread 6.00% Total Coupon 11.37% "
            "Maturity 11/9/2029"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": self._BLACKROCK_PRIVATE_CREDIT_CIK,
            "fair_value": 7209657,
            "cost": 7325923,
            "principal_amount": 7250000,
            "interest_rate": 0.1137,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == raw
        assert pd.isna(row["instrument_description"]) or row["instrument_description"] == ""

    def test_blackrock_private_credit_glued_equity_prefix_extracts_issuer(self):
        """BlackRock glued Equity Securities prefix parses a real equity issuer."""
        raw = "Equity SecuritiesMedia Streamland Media Holdings LLC Instrument Common Stock"
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": self._BLACKROCK_PRIVATE_CREDIT_CIK,
            "fair_value": 1170726,
            "cost": 1170726,
            "shares_held": 1000,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Streamland Media Holdings LLC"
        assert row["instrument_description"] == "Common Stock"

    def test_new_mountain_comma_undrawn_extracts_issuer_and_instrument(self):
        """New Mountain comma-only rows keep First Lien in instrument text."""
        raw = "Centegix Intermediate II, LLC, First Lien - Undrawn 1"
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0002037804",
            "fair_value": 1000,
            "cost": 1000,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Centegix Intermediate II, LLC"
        assert row["instrument_description"] == "First Lien - Undrawn 1"

    def test_new_mountain_no_comma_lien_extracts_issuer_and_instrument(self):
        """New Mountain no-comma legal suffix rows split before First Lien."""
        raw = "Al Altius US Bidco, Inc. First Lien"
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0002037804",
            "fair_value": 1000,
            "cost": 1000,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Al Altius US Bidco, Inc."
        assert row["instrument_description"] == "First Lien"

    def test_new_mountain_parenthetical_issuer_extracts_before_lien(self):
        """New Mountain rows with fka parentheticals keep the alias on issuer."""
        raw = "Auctane Inc. (fka Stamps.com Inc.), First Lien 1"
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0002037804",
            "fair_value": 1000,
            "cost": 1000,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Auctane Inc. (fka Stamps.com Inc.)"
        assert row["instrument_description"] == "First Lien 1"

    def test_kkr_fs_select_comma_row_extracts_issuer_and_instrument(self):
        """KKR Select comma rows split issuer before industry/tranche text."""
        raw = "Carrier Fire Protection, Commercial & Professional Services 1"
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001975736",
            "fair_value": 1000,
            "cost": 1000,
            "principal_amount": 1000,
            "basis_spread": 0.045,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Carrier Fire Protection"
        assert row["instrument_description"] == "Commercial & Professional Services 1"

    def test_kkr_fs_select_pipe_row_extracts_issuer_and_instrument(self):
        """KKR Select pipe rows retain issuer and industry/tranche text."""
        raw = "A-Lign Assurance LLC | Software & Services 1"
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001975736",
            "fair_value": 1000,
            "cost": 1000,
            "principal_amount": 1000,
            "basis_spread": 0.045,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "A-Lign Assurance LLC"
        assert row["instrument_description"] == "Software & Services 1"

    def test_kkr_fs_select_affiliated_pipe_prefix_extracts_real_issuer(self):
        """Affiliated Issuer prefixes are not retained as issuer names."""
        raw = "Affiliated Issuer | Discover Financial Services, Subordinated Loan"
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001975736",
            "fair_value": 1000,
            "cost": 1000,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Discover Financial Services"
        assert row["instrument_description"] == "Subordinated Loan"

    def test_jefferies_hierarchy_extracts_debt_issuer_and_instrument(self):
        """Jefferies flattened hierarchy rows split issuer before Investment Type."""
        raw = (
            "Non-Controlled/Non-Affiliated Portfolio Company Investments First Lien "
            "Debt Investments Aerospace & Defense AA&D Midco, Inc. "
            "(fka GB Eagle Buyer, Inc.) Investment Type First Lien Term Loan "
            "Reference Rate and Spread S + 4.75% Maturity Date 11/29/2030"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001959604",
            "fair_value": 1000,
            "cost": 1000,
            "principal_amount": 1000,
            "basis_spread": 0.0475,
            "maturity_date": "2030-11-29",
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "AA&D Midco, Inc. (fka GB Eagle Buyer, Inc.)"
        assert row["instrument_description"] == "First Lien Term Loan"

    def test_jefferies_hierarchy_extracts_lp_interest_leaf(self):
        """Jefferies L.P. interest rows survive as equity positions."""
        raw = (
            "Non-Controlled/Non-Affiliated Portfolio Company Investments Equity "
            "Investments L.P Interests Commercial Services & Supplies Firebird "
            "Co-Invest L.P Investment Type L.P Interest"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001959604",
            "fair_value": 537000,
            "cost": 434000,
            "shares_held": 0,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Firebird Co-Invest L.P"
        assert row["instrument_description"] == "L.P Interest"
        assert row["asset_category"] == "FUND"

    def test_jefferies_unfunded_commitment_total_is_dropped(self):
        """Jefferies unfunded commitment totals are not position leaves."""
        df = self._make_bdc_df([{
            "investment_identifier": "Total Unfunded Portfolio Company Commitments",
            "cik": "0001959604",
            "fair_value": -1982000,
        }])

        result = _prepare_bdc(df)

        assert result.empty

    def test_antares_private_hierarchy_extracts_debt_issuer_and_instrument(self):
        """Antares Private Asset Type rows split issuer before the leaf instrument."""
        raw = (
            "Investments - non-controlled/non-affiliated Secured Debt Aerospace and Defense "
            "Bleriot US Bidco Inc. Asset Type First Lien Term Loan Reference Rate and "
            "Spread S + 2.50% Interest Rate 6.17% Maturity Date 10/31/2030"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001976336",
            "fair_value": 3629000,
            "cost": 3600000,
            "principal_amount": 3700000,
            "basis_spread": 0.025,
            "interest_rate": 0.0617,
            "maturity_date": "2030-10-31",
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Bleriot US Bidco Inc."
        assert "First Lien Term Loan" in row["instrument_description"]

    def test_antares_private_hierarchy_extracts_commitment_issuer(self):
        """Antares Private Commitment Type rows are issuer-level positions."""
        raw = (
            "Investments\u2014non-controlled/non-affiliated Inhabitiq Inc. Commitment Type "
            "Delayed Draw Term Loan Commitment Expiration Date 1/11/2027"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001976336",
            "fair_value": -5000,
            "cost": 0,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Inhabitiq Inc."
        assert "Delayed Draw Term Loan" in row["instrument_description"]

    def test_antares_private_hierarchy_extracts_commitment_without_type_label(self):
        """Commitment rows missing the Commitment Type label still split cleanly."""
        raw = (
            "Investments\u2014non-controlled/non-affiliated Noble Midco 3 Limited "
            "Revolver Commitment Expiration Date 12/10/2030"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001976336",
            "fair_value": -1000,
            "cost": 0,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Noble Midco 3 Limited"
        assert row["instrument_description"].startswith("Revolver")

    def test_antares_private_hierarchy_extracts_no_space_asset_type(self):
        """Malformed Asset TypeFirst strings still split issuer and instrument."""
        raw = (
            "Secured Debt Media MH Sub I, LLC Asset TypeFirst Lien Term Loan "
            "Reference Rate and SpreadS + 4.25% Interest Rate 8.57% "
            "Maturity Date12/31/2031"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001976336",
            "fair_value": 2298000,
            "cost": 2300000,
            "principal_amount": 2300000,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "MH Sub I, LLC"
        assert "First Lien Term Loan" in row["instrument_description"]

    def test_antares_private_hierarchy_extracts_assets_type_plural(self):
        """Plural Assets Type rows split issuer and instrument."""
        raw = (
            "Secured Debt Professional Services HSI Halo Acquisition Inc. Assets Type "
            "First Lien Term Loan Reference Rate and Spread S + 5.00% Interest Rate "
            "9.13% Maturity Date 6/30/2031"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001976336",
            "fair_value": 7767000,
            "cost": 7700000,
            "principal_amount": 7800000,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "HSI Halo Acquisition Inc."
        assert "First Lien Term Loan" in row["instrument_description"]

    def test_antares_private_hierarchy_extracts_stripped_debt_investments_prefix(self):
        """Already stripped Debt Investments hierarchy rows do not leak into issuer."""
        raw = (
            "Debt Investments Diversified Consumer Services Apex Service Partners "
            "Intermediate 2, LLC Asset Type Subordinated Unsecured Delayed Draw "
            "Term Loan Interest Rate 14.25% Maturity Date 4/23/2031"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": "0001976336",
            "fair_value": 728000,
            "cost": 725000,
            "principal_amount": 730000,
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "Apex Service Partners Intermediate 2, LLC"
        assert "Subordinated Unsecured" in row["instrument_description"]

    def test_antares_private_industry_heading_is_dropped(self):
        """Antares Private industry-only secured-debt headings are not leaves."""
        df = self._make_bdc_df([{
            "investment_identifier": (
                "Investments - non-controlled/non-affiliated Secured Debt IT Services"
            ),
            "cik": "0001976336",
            "fair_value": 39730000,
            "cost": 39817000,
        }])

        result = _prepare_bdc(df)

        assert result.empty

    def test_audax_hierarchy_numeric_issuer_is_not_replaced_by_raw(self):
        """Configured hierarchy_extract rows may have digit-heavy issuers."""
        raw = (
            "Portfolio Investments Audax Credit BDC, Inc. BANK LOANS: "
            "NON-CONTROL/NON-AFFILIATE INVESTMENTS Capital Equipment 80/20 "
            "Investment Type Unitranche Initial Term Loan Index S+ Spread 4.50% "
            "Interest Rate 8.18% Acquisition Date 12/11/2025 Maturity Date 12/12/2032"
        )
        df = self._make_bdc_df([{
            "investment_identifier": raw,
            "cik": self._AUDAX_CIK,
            "fair_value": 677618,
            "cost": 674978,
            "principal_amount": 682540,
            "interest_rate": 0.0818,
            "basis_spread": 0.045,
            "maturity_date": "2032-12-12",
        }])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "80/20"
        assert row["instrument_description"].startswith("Unitranche Initial Term Loan")

    def test_audax_equity_header_dropped_but_numeric_issuer_leaf_kept(self):
        """Audax category headers without Investment Type are not positions."""
        header = (
            "Portfolio Investments EQUITY AND PREFERRED SHARES: NON-CONTROL/NON-AFFILIATE "
            "INVESTMENTS- (1.6%) Wholesale"
        )
        leaf = (
            "Portfolio Investments EQUITY AND PREFERRED SHARES: NON-CONTROL/NON-AFFILIATE "
            "INVESTMENTS Capital Equipment 80/20 Investment Type LP Interest "
            "Acquisition Date 12/11/2025"
        )
        df = self._make_bdc_df([
            {
                "investment_identifier": header,
                "cik": self._AUDAX_CIK,
                "fair_value": 7190615,
                "cost": 7190615,
            },
            {
                "investment_identifier": leaf,
                "cik": self._AUDAX_CIK,
                "fair_value": 9431,
                "cost": 10000,
                "shares_held": 10000,
            },
        ])

        result = _prepare_bdc(df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["issuer_name"] == "80/20"
        assert row["instrument_description"].startswith("LP Interest")
        assert float(row["fair_value"]) == 9431

    def test_msd_glued_uppercase_hierarchy_parses_real_issuers(self):
        """MSD uppercase/glued hierarchy labels should not pollute issuer names."""
        rows = [
            {
                "investment_identifier": (
                    "INVESTMENTS INVESTMENTS - NON-CONTROLLED/NON-AFFILIATED "
                    "SECOND LIEN DEBT SERVICESConsumer Southern Veterinary Partners L L C "
                    "Reference Rate and Spread S + 7.85% Interest Rate Floor 1.00% "
                    "Interest Rate 12.25% Maturity Date 10/5/2028"
                ),
                "fair_value": 45000000,
                "cost": 44264000,
                "principal_amount": 45000000,
                "interest_rate": 0.1225,
            },
            {
                "investment_identifier": (
                    "INVESTMENTS INVESTMENTS - NON-CONTROLLED/NON-AFFILIATED "
                    "Preferred Equity CONSUMER GOODSNon-durable Protective Industrial "
                    "Products Inc. - Series A Preferred Interest Rate 13.00% P I K"
                ),
                "fair_value": 36309000,
                "cost": 35831000,
            },
            {
                "investment_identifier": (
                    "INVESTMENTS INVESTMENTS - NON-CONTROLLED/NON-AFFILIATED "
                    "Preferred Equity SERVICES Consumer Metropolis Technologies Inc. "
                    "- Warrant Maturity Date 2/13/2034"
                ),
                "fair_value": 215000,
                "cost": 189000,
            },
            {
                "investment_identifier": (
                    "Investments Investments - non-controlled/non-affiliated "
                    "First Lien Debt Services: ConsumerInvestments Investments - "
                    "non-controlled/non-affiliated Second Lien Debt Services: Consumer "
                    "Midwest Veterinary Partners LLC Reference Rate and Spread S + 7.60% "
                    "Interest Rate Floor 0.75% Interest Rate 12.71% Maturity Date 4/26/2029"
                ),
                "fair_value": 35134000,
                "cost": 35709000,
                "principal_amount": 35714000,
                "interest_rate": 0.1271,
            },
        ]
        df = self._make_bdc_df([
            {"cik": self._MSD_CIK, **row} for row in rows
        ])

        result = _prepare_bdc(df)

        issuers = set(result["issuer_name"])
        assert "Southern Veterinary Partners L L C" in issuers
        assert "Protective Industrial Products Inc." in issuers
        assert "Metropolis Technologies Inc." in issuers
        assert "Midwest Veterinary Partners LLC" in issuers
        assert "INVESTMENTS INVESTMENTS" not in issuers
        assert "ConsumerInvestments Investments" not in issuers
        assert not any(str(issuer).startswith("GOODSNon") for issuer in issuers)


class TestApplyWrapperPositionKeys:
    """Tests for _apply_wrapper_position_keys: override position_key with
    wrapper-generated keys for wrapped BDC CIKs."""

    def test_empty_df(self):
        """Empty DataFrame passes through unchanged."""
        df = pd.DataFrame()
        result = _apply_wrapper_position_keys(df)
        assert result.empty

    def test_nport_rows_unaffected(self):
        """N-PORT rows should never have position_key overridden."""
        df = pd.DataFrame({
            "source": ["nport"],
            "cik": ["0001287750"],
            "position_key": ["original_key"],
            "bdc_investment_identifier": [""],
        })
        result = _apply_wrapper_position_keys(df)
        assert result.iloc[0]["position_key"] == "original_key"

    def test_non_wrapped_cik_unaffected(self):
        """BDC CIK without a wrapper should keep staging position_key."""
        df = pd.DataFrame({
            "source": ["bdc"],
            "cik": ["9999999999"],  # No wrapper exists for this CIK
            "position_key": ["original_key"],
            "bdc_investment_identifier": ["Acme Corp - Term Loan"],
        })
        result = _apply_wrapper_position_keys(df)
        assert result.iloc[0]["position_key"] == "original_key"

    def test_wrapped_cik_position_key_overridden(self):
        """Wrapped CIK with a recognized identifier gets position_key
        replaced by wrapper_position_key."""
        # Use Sixth Street Specialty Lending (0001508655) which has prefix
        # rules.  The identifier must start with a registered prefix and
        # contain at least one leaf marker to get disposition=*_position_leaf.
        df = pd.DataFrame({
            "source": ["bdc"],
            "cik": ["0001508655"],
            "position_key": ["generic_staging_key"],
            "bdc_investment_identifier": [
                "Debt Investments Business Services Acme Corp "
                "First Lien Term Loan Interest Rate 10.0%"
            ],
        })
        result = _apply_wrapper_position_keys(df)
        new_key = result.iloc[0]["position_key"]
        # Wrapper key should differ from the generic staging key
        assert new_key != "generic_staging_key"
        # Wrapper normalizes to lowercase alphanumeric
        assert new_key == new_key.lower()
        assert "acme" in new_key

    def test_goldman_duplicate_wrapper_keys_get_lot_suffixes(self):
        """Repeated Goldman wrapper keys stay separate position-level lots."""
        identifier = (
            "Investment 1st Lien/Senior Secured Debt - 203.92% "
            "AQ Helios Buyer, Inc. (dba SurePoint) Industry Software "
            "Interest Rate 11.96% Reference Rate and Spread S + 7.00% "
            "Maturity 07/01/26"
        )
        df = pd.DataFrame({
            "source": ["bdc", "bdc", "bdc"],
            "cik": ["0001772704", "0001772704", "0001772704"],
            "report_date": ["2023-03-31", "2023-03-31", "2023-06-30"],
            "position_key": ["generic_1", "generic_2", "generic_3"],
            "bdc_investment_identifier": [identifier, identifier, identifier],
            "principal_amount": [100.0, 50.0, 100.0],
            "fair_value": [99000.0, 49000.0, 101000.0],
            "cost": [100000.0, 50000.0, 100000.0],
        })

        result = _apply_wrapper_position_keys(df)

        keys = list(result["position_key"])
        assert keys[0].endswith(" lot 1")
        assert keys[1].endswith(" lot 2")
        assert not keys[2].endswith(" lot 1")
        assert keys[0].replace(" lot 1", "") == keys[1].replace(" lot 2", "")

    def test_varagon_duplicate_wrapper_keys_get_lot_suffixes(self):
        """Repeated Varagon loans remain separate lots after spread stripping."""
        base_identifier = (
            "Non-Controlled/Non-Affiliated Investments, Senior Secured First Lien Loans, "
            "Company Arrowhead Holdco Company, Industry Auto Components, Type of "
            "Investment Term Loan, Reference Rate and Spread SOFR+4.50%, Interest "
            "Rate 9.28%, Maturity 08/31/28"
        )
        df = pd.DataFrame({
            "source": ["bdc", "bdc", "bdc"],
            "cik": ["0001784700", "0001784700", "0001784700"],
            "report_date": ["2023-03-31", "2023-03-31", "2023-06-30"],
            "position_key": ["generic_1", "generic_2", "generic_3"],
            "bdc_investment_identifier": [base_identifier, base_identifier, base_identifier],
            "principal_amount": [100.0, 50.0, 100.0],
            "fair_value": [99000.0, 49000.0, 101000.0],
            "cost": [100000.0, 50000.0, 100000.0],
        })

        result = _apply_wrapper_position_keys(df)

        keys = list(result["position_key"])
        assert keys[0].endswith(" lot 1")
        assert keys[1].endswith(" lot 2")
        assert not keys[2].endswith(" lot 1")
        assert keys[0].replace(" lot 1", "") == keys[1].replace(" lot 2", "")

    def test_no_source_column_returns_unchanged(self):
        """DataFrame without 'source' column passes through safely."""
        df = pd.DataFrame({
            "cik": ["0001287750"],
            "position_key": ["key"],
        })
        result = _apply_wrapper_position_keys(df)
        assert result.iloc[0]["position_key"] == "key"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_apollo_origination_ii_l_hierarchy_extracts_issuer_and_instrument():
    raw = (
        "Automobile Components Clarience Technologies Truck-Lite Co., LLC "
        "Investment Type First Lien Secured Debt - Delayed Draw Interest Rate "
        "S+575, 0.75% Floor Maturity Date 2/13/2031"
    )
    df = pd.DataFrame([{
        "cik": "0002052152",
        "entity_name": "Apollo Origination II (L) Capital Trust",
        "accession_number": "0002052152-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 1115000,
        "cost": 1115000,
        "principal_amount": 1115000,
        "interest_rate": 0.1,
        "basis_spread": 0.0575,
        "reference_rate_type": "",
        "maturity_date": "2031-02-13",
        "pct_of_net_assets": 0.001,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Clarience Technologies Truck-Lite Co., LLC"
    assert row["instrument_description"].startswith(
        "First Lien Secured Debt - Delayed Draw"
    )
    assert "Investment Type" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_apollo_origination_ii_ul_hierarchy_extracts_extended_industry_label():
    raw = (
        "Technology Hardware, Storage & Peripherals Service Express "
        "Victors Purchaser, LLC Investment Type First Lien Secured Debt - "
        "Term Loan Interest Rate S+550, 0.50% Floor Maturity Date 2/3/2031"
    )
    df = pd.DataFrame([{
        "cik": "0002052153",
        "entity_name": "Apollo Origination II (UL) Capital Trust",
        "accession_number": "0002052153-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 1115000,
        "cost": 1115000,
        "principal_amount": 1115000,
        "interest_rate": 0.1,
        "basis_spread": 0.055,
        "reference_rate_type": "",
        "maturity_date": "2031-02-03",
        "pct_of_net_assets": 0.001,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Service Express Victors Purchaser, LLC"
    assert row["instrument_description"].startswith(
        "First Lien Secured Debt - Term Loan"
    )
    assert "Technology Hardware" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_vista_credit_strategic_lending_hierarchy_extracts_issuer_and_instrument():
    raw = (
        "Investments \u2013 non-controlled/non-affiliated First-Lien Debt Data & Analytics "
        "Azurite Intermediate Holdings, Inc. Reference Rate and Spread SOFR + 6.00% "
        "Interest Rate 10.33% Maturity Date 3/19/2031"
    )
    equity_raw = (
        "Investments Preferred Equity Transportation, Logistics & Supply Chain "
        "Metropolis Technologies, Inc. Interest Rate 16.00% Maturity Date 5/14/2036"
    )
    df = pd.DataFrame([
        {
            "cik": "0001919369",
            "entity_name": "Vista Credit Strategic Lending Corp.",
            "accession_number": "0001919369-26-000001",
            "form_type": "10-Q",
            "filing_date": "2026-05-01",
            "report_date": "2026-03-31",
            "investment_identifier": raw,
            "fair_value": 12000000,
            "cost": 11900000,
            "principal_amount": 12000000,
            "interest_rate": 0.1033,
            "basis_spread": 0.06,
            "reference_rate_type": "",
            "maturity_date": "2031-03-19",
            "pct_of_net_assets": 0.01,
            "pik_rate": "",
            "shares_held": "",
            "unrealized_gain_loss": "",
            "dimensions_raw": "",
            "investment_type": "",
            "industry": "",
            "affiliation": "",
        },
        {
            "cik": "0001919369",
            "entity_name": "Vista Credit Strategic Lending Corp.",
            "accession_number": "0001919369-26-000001",
            "form_type": "10-Q",
            "filing_date": "2026-05-01",
            "report_date": "2026-03-31",
            "investment_identifier": equity_raw,
            "fair_value": 5000000,
            "cost": 5000000,
            "principal_amount": "",
            "interest_rate": 0.16,
            "basis_spread": "",
            "reference_rate_type": "",
            "maturity_date": "2036-05-14",
            "pct_of_net_assets": 0.004,
            "pik_rate": "",
            "shares_held": "",
            "unrealized_gain_loss": "",
            "dimensions_raw": "",
            "investment_type": "",
            "industry": "",
            "affiliation": "",
        },
    ])

    result = _prepare_bdc(df)

    assert len(result) == 2
    by_issuer = {row["issuer_name"]: row for _, row in result.iterrows()}
    assert "Azurite Intermediate Holdings, Inc." in by_issuer
    assert by_issuer["Azurite Intermediate Holdings, Inc."]["instrument_description"] == (
        "First-Lien Debt"
    )
    assert "Metropolis Technologies, Inc." in by_issuer
    assert by_issuer["Metropolis Technologies, Inc."]["instrument_description"] == (
        "Preferred Equity"
    )
    assert "Investments" not in " ".join(result["issuer_name"])


@pytest.mark.slow
@pytest.mark.staging_sql
def test_t_series_bdc_hierarchy_extracts_debt_issuer_and_instrument():
    raw = (
        "Debt Investments - non-controlled/non-affiliated Software "
        "Anaplan, Inc. First Lien Debt Reference Rate and Spread S + 4.50% "
        "Interest Rate 8.70% Maturity Date 06/21/2029"
    )
    df = pd.DataFrame([{
        "cik": "0001885968",
        "entity_name": "T Series BDC LLC",
        "accession_number": "0001885968-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 21517000,
        "cost": 21287000,
        "principal_amount": 21517000,
        "interest_rate": 0.087,
        "basis_spread": 0.045,
        "reference_rate_type": "",
        "maturity_date": "2029-06-21",
        "pct_of_net_assets": 0.0194,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Anaplan, Inc."
    assert row["instrument_description"].startswith("First Lien Debt")
    assert "Debt Investments" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_t_series_bdc_axis_label_hierarchy_extracts_debt_issuer():
    raw = (
        "Investment, Identifier [Axis]: Debt Investments - non-controlled/non-affiliated "
        "Health Care Providers & Services Pareto Health Intermediate Holdings, Inc. "
        "First Lien Debt Reference Rate and Spread S + 4.75% Interest Rate 0.0875 "
        "Maturity Date 06/01/2029"
    )
    df = pd.DataFrame([{
        "cik": "0001885968",
        "entity_name": "T Series BDC LLC",
        "accession_number": "0001885968-25-000001",
        "form_type": "10-Q",
        "filing_date": "2025-11-12",
        "report_date": "2025-09-30",
        "investment_identifier": raw,
        "fair_value": 0,
        "cost": -33000,
        "principal_amount": 0,
        "interest_rate": 0.0875,
        "basis_spread": 0.0475,
        "reference_rate_type": "",
        "maturity_date": "2029-06-01",
        "pct_of_net_assets": 0,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Pareto Health Intermediate Holdings, Inc."
    assert row["instrument_description"].startswith("First Lien Debt")


@pytest.mark.slow
@pytest.mark.staging_sql
def test_t_series_bdc_hierarchy_extracts_equity_issuer_and_instrument():
    raw = (
        "Equity Investments - non-controlled/non-affiliated Insurance Services "
        "Amerilife Holdings, LLC Common Equity Acquisition Date 09/01/2022"
    )
    df = pd.DataFrame([{
        "cik": "0001885968",
        "entity_name": "T Series BDC LLC",
        "accession_number": "0001885968-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 1000000,
        "cost": 900000,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.01,
        "pik_rate": "",
        "shares_held": 1000,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Amerilife Holdings, LLC"
    assert row["instrument_description"].startswith("Common Equity")


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_vii_hierarchy_extracts_debt_issuer_and_instrument():
    raw = (
        "Debt Securities Food Products Hometown Food Company Acquisition Date "
        "08/31/18 Term Loan - 10.21% (SOFR + 5.00%, 1.25% Floor) "
        "% of Net Assets 2.6% Maturity Date 08/31/23"
    )
    df = pd.DataFrame([{
        "cik": "0001715933",
        "entity_name": "TCW Direct Lending VII LLC",
        "accession_number": "0001715933-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 16752204,
        "cost": 16800000,
        "principal_amount": 17000000,
        "interest_rate": 0.1021,
        "basis_spread": 0.05,
        "reference_rate_type": "",
        "maturity_date": "2023-08-31",
        "pct_of_net_assets": 0.026,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Hometown Food Company"
    assert row["instrument_description"] == "Term Loan"
    assert "Debt Securities" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_vii_hierarchy_extracts_affiliated_debt():
    raw = (
        "Controlled Affiliated Investments Navistar Defense, LLC "
        "Super Senior Revolver - 14.27% inc PIK"
    )
    df = pd.DataFrame([{
        "cik": "0001715933",
        "entity_name": "TCW Direct Lending VII LLC",
        "accession_number": "0001715933-26-000002",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 12500000,
        "cost": 13000000,
        "principal_amount": 15000000,
        "interest_rate": 0.1427,
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": "",
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Navistar Defense, LLC"
    assert row["instrument_description"] == "Super Senior Revolver"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_vii_hierarchy_extracts_equity_security():
    raw = (
        "Equity Securities Textiles, Apparel & Luxury Goods Centric Brands "
        "L.P. Class A LP Interests"
    )
    df = pd.DataFrame([{
        "cik": "0001715933",
        "entity_name": "TCW Direct Lending VII LLC",
        "accession_number": "0001715933-26-000003",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 4025000,
        "cost": 1000000,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": "",
        "pik_rate": "",
        "shares_held": 100,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Centric Brands L.P."
    assert row["instrument_description"] == "Class A LP Interests"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_viii_hierarchy_extracts_debt_issuer_and_instrument():
    raw = (
        "Debt Investments, Commercial Services & Supplies Power Acquisition LLC, "
        "Acquisition Date 01/22/25 Term Loan B - 10.67% "
        "(SOFR + 7.00%, 1.50% Floor) Net Assets 4.2% Maturity 01/22/30"
    )
    df = pd.DataFrame([{
        "cik": "0001825265",
        "entity_name": "TCW Direct Lending VIII LLC",
        "accession_number": "0001825265-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 33856766,
        "cost": 33702547,
        "principal_amount": 34000000,
        "interest_rate": 0.1067,
        "basis_spread": 0.07,
        "reference_rate_type": "",
        "maturity_date": "2030-01-22",
        "pct_of_net_assets": 0.042,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Power Acquisition LLC"
    assert row["instrument_description"] == "Term Loan B"
    assert "Debt Investments" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_viii_hierarchy_extracts_equity_warrant():
    raw = (
        "Equity Investments, Energy Equipment & Services HydroSource Logistics, LLC, "
        "Acquisition Date 04/05/24 Warrant, expires 4/4/34 Net Assets 3.5%"
    )
    df = pd.DataFrame([{
        "cik": "0001825265",
        "entity_name": "TCW Direct Lending VIII LLC",
        "accession_number": "0001825265-26-000002",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 28719739,
        "cost": 357421,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.035,
        "pik_rate": "",
        "shares_held": 247,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "HydroSource Logistics, LLC"
    assert row["instrument_description"] == "Warrant, expires 4/4/34"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_viii_hierarchy_extract_is_cik_scoped():
    raw = (
        "Debt Investments, Commercial Services & Supplies Power Acquisition LLC, "
        "Acquisition Date 01/22/25 Term Loan B - 10.67% "
        "(SOFR + 7.00%, 1.50% Floor) Net Assets 4.2% Maturity 01/22/30"
    )
    df = pd.DataFrame([{
        "cik": "0001603480",
        "entity_name": "TCW Direct Lending LLC",
        "accession_number": "0001603480-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 33856766,
        "cost": 33702547,
        "principal_amount": 34000000,
        "interest_rate": 0.1067,
        "basis_spread": 0.07,
        "reference_rate_type": "",
        "maturity_date": "2030-01-22",
        "pct_of_net_assets": 0.042,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    assert result.iloc[0]["issuer_name"] != "Power Acquisition LLC"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_llc_hierarchy_extracts_debt_issuer_and_instrument():
    raw = (
        "Debt Investments- United States Distributors Animal Supply Company, LLC "
        "Date 08/14/20 Term Loan - 13.16% inc PIK "
        "(SOFR + 8.50%, 1.00% Floor, all PIK) Net Assets 5.8% "
        "Maturity 08/14/25"
    )
    df = pd.DataFrame([{
        "cik": "0001603480",
        "entity_name": "TCW Direct Lending LLC",
        "accession_number": "0001603480-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 42400000,
        "cost": 42000000,
        "principal_amount": 43000000,
        "interest_rate": 0.1316,
        "basis_spread": 0.085,
        "reference_rate_type": "",
        "maturity_date": "2025-08-14",
        "pct_of_net_assets": 0.058,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Animal Supply Company, LLC"
    assert row["instrument_description"] == "Term Loan"
    assert "Debt Investments" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_llc_hierarchy_extracts_equity_membership_interest():
    raw = (
        "Equity Investments- United States Investment Funds & Vehicles "
        "TCW Direct Lending Strategic Ventures Preferred membership Interests "
        "Net Assets 20.9%"
    )
    df = pd.DataFrame([{
        "cik": "0001603480",
        "entity_name": "TCW Direct Lending LLC",
        "accession_number": "0001603480-26-000002",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 82000000,
        "cost": 82000000,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.209,
        "pik_rate": "",
        "shares_held": 100,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "TCW Direct Lending Strategic Ventures"
    assert row["instrument_description"] == "Preferred membership Interests"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_llc_hierarchy_extracts_class_common():
    raw = (
        "Equity Investments- United States Distributors "
        "Retail & Animal Supply Holdings, LLC Class A Common Net Assets 1.2%"
    )
    df = pd.DataFrame([{
        "cik": "0001603480",
        "entity_name": "TCW Direct Lending LLC",
        "accession_number": "0001603480-26-000003",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 1200000,
        "cost": 1000000,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.012,
        "pik_rate": "",
        "shares_held": 100,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Retail & Animal Supply Holdings, LLC"
    assert row["instrument_description"] == "Class A Common"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_llc_hierarchy_extracts_bare_debt_row():
    raw = "Animal Supply Company, LLC First Out Term Loan - 13.09%"
    df = pd.DataFrame([{
        "cik": "0001603480",
        "entity_name": "TCW Direct Lending LLC",
        "accession_number": "0001603480-26-000004",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 2703724,
        "cost": 2703724,
        "principal_amount": "",
        "interest_rate": 0.1309,
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "2025-08-14",
        "pct_of_net_assets": "",
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Animal Supply Company, LLC"
    assert row["instrument_description"] == "First Out Term Loan"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_direct_lending_llc_hierarchy_extracts_bare_equity_row():
    raw = "TCW Direct Lending Strategic Ventures LLC Preferred Membership Interests"
    df = pd.DataFrame([{
        "cik": "0001603480",
        "entity_name": "TCW Direct Lending LLC",
        "accession_number": "0001603480-26-000005",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 37189488,
        "cost": 37189488,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": "",
        "pik_rate": "",
        "shares_held": 100,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "TCW Direct Lending Strategic Ventures LLC"
    assert row["instrument_description"] == "Preferred Membership Interests"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_star_direct_lending_hierarchy_extracts_debt_issuer_and_instrument():
    raw = (
        "Debt Investment Commercial Services & Supplies Jones Industrial Holdings, Inc. "
        "Acquisition Date - 07/31/2023 Investment Term Loan - 13.92% "
        "(SOFR + 8.50%, 2.00% Floor) % of Net Assets - 6.6% "
        "Maturity Date - 07/31/2028"
    )
    df = pd.DataFrame([{
        "cik": "0001916608",
        "entity_name": "TCW Star Direct Lending LLC",
        "accession_number": "0001916608-24-000001",
        "form_type": "10-Q",
        "filing_date": "2024-05-01",
        "report_date": "2024-03-31",
        "investment_identifier": raw,
        "fair_value": 12345678,
        "cost": 12300000,
        "principal_amount": 12500000,
        "interest_rate": 0.1392,
        "basis_spread": 0.085,
        "reference_rate_type": "",
        "maturity_date": "2028-07-31",
        "pct_of_net_assets": 0.066,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Jones Industrial Holdings, Inc."
    assert row["instrument_description"] == "Term Loan"
    assert "Debt Investment" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_star_direct_lending_hierarchy_extracts_equity_warrant():
    raw = (
        "Equity Investment, Automobile Components SUP Parent Holdings, LLC "
        "Acquisition Date - 08/13/25 Investment Common Units % of Net Assets - 0.8%"
    )
    df = pd.DataFrame([{
        "cik": "0001916608",
        "entity_name": "TCW Star Direct Lending LLC",
        "accession_number": "0001916608-26-000001",
        "form_type": "10-K",
        "filing_date": "2026-03-01",
        "report_date": "2025-12-31",
        "investment_identifier": raw,
        "fair_value": 1658228,
        "cost": 0,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.008,
        "pik_rate": "",
        "shares_held": 100,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "SUP Parent Holdings, LLC"
    assert row["instrument_description"] == "Common Units"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_tcw_star_direct_lending_malformed_no_issuer_row_not_extracted_as_position():
    raw = (
        "Debt Investment Date Processing And Outsourced Services Acquisition Date - "
        "12/21/22 Term Loan 11.57% (SOFR+6.88% 1.50% Floor) Maturity Date 12/21/27"
    )
    df = pd.DataFrame([{
        "cik": "0001916608",
        "entity_name": "TCW Star Direct Lending LLC",
        "accession_number": "0001916608-23-000001",
        "form_type": "10-Q",
        "filing_date": "2023-05-01",
        "report_date": "2023-03-31",
        "investment_identifier": raw,
        "fair_value": 10150263,
        "cost": 10100000,
        "principal_amount": 10200000,
        "interest_rate": 0.1157,
        "basis_spread": 0.0688,
        "reference_rate_type": "",
        "maturity_date": "2027-12-21",
        "pct_of_net_assets": "",
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 0


@pytest.mark.slow
@pytest.mark.staging_sql
def test_commonwealth_credit_partners_hierarchy_extracts_debt_issuer_and_instrument():
    raw = (
        "Debt Investments, First Lien Senior Secured, National Debt Relief - "
        "Term Loan, Diversified Financials, Spread Above Index SOFR + 6.00% "
        "(1.50% Floor) Interest rate 11.47% Maturity Date 2/24/2027"
    )
    df = pd.DataFrame([{
        "cik": "0001841514",
        "entity_name": "Commonwealth Credit Partners BDC I, Inc.",
        "accession_number": "0000950170-24-029358",
        "form_type": "10-K",
        "filing_date": "2024-03-11",
        "report_date": "2023-12-31",
        "investment_identifier": raw,
        "fair_value": 12961000,
        "cost": 12970000,
        "principal_amount": 13131000,
        "interest_rate": 0.1147,
        "basis_spread": 0.06,
        "reference_rate_type": "",
        "maturity_date": "2027-02-24",
        "pct_of_net_assets": 0.02,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "National Debt Relief"
    assert row["instrument_description"] == "Term Loan"
    assert "Debt Investments" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_commonwealth_credit_partners_hierarchy_extracts_revolving_credit_line():
    raw = (
        "Debt Investments, First Lien Senior Secured, OAO Acquisitions - "
        "Revolving Credit Line, Capital Goods, Spread Above Index SOFR + "
        "6.25% (1.25% floor), Interest rate 11.60%, Maturity Date 12/27/2029"
    )
    df = pd.DataFrame([{
        "cik": "0001841514",
        "entity_name": "Commonwealth Credit Partners BDC I, Inc.",
        "accession_number": "0000950170-24-029358",
        "form_type": "10-K",
        "filing_date": "2024-03-11",
        "report_date": "2023-12-31",
        "investment_identifier": raw,
        "fair_value": -10000,
        "cost": 10000,
        "principal_amount": 0,
        "interest_rate": 0.116,
        "basis_spread": 0.0625,
        "reference_rate_type": "",
        "maturity_date": "2029-12-27",
        "pct_of_net_assets": 0,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "OAO Acquisitions"
    assert row["instrument_description"] == "Revolving Credit Line"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_commonwealth_credit_partners_hierarchy_extracts_equity_shorthand():
    raw = "CTM Acquisition LLC Equity, Media & Entertainment"
    df = pd.DataFrame([{
        "cik": "0001841514",
        "entity_name": "Commonwealth Credit Partners BDC I, Inc.",
        "accession_number": "0000950170-24-096491",
        "form_type": "10-Q",
        "filing_date": "2024-08-14",
        "report_date": "2024-06-30",
        "investment_identifier": raw,
        "fair_value": 269000,
        "cost": 665000,
        "principal_amount": 664865000,
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.0004,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "CTM Acquisition LLC"
    assert row["instrument_description"] == "Equity"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_commonwealth_credit_partners_hierarchy_extract_is_cik_scoped():
    raw = (
        "Debt Investments, First Lien Senior Secured, National Debt Relief - "
        "Term Loan, Diversified Financials, Spread Above Index SOFR + 6.00% "
        "(1.50% Floor) Interest rate 11.47% Maturity Date 2/24/2027"
    )
    df = pd.DataFrame([{
        "cik": "0001603480",
        "entity_name": "TCW Direct Lending LLC",
        "accession_number": "0001603480-24-000001",
        "form_type": "10-K",
        "filing_date": "2024-03-11",
        "report_date": "2023-12-31",
        "investment_identifier": raw,
        "fair_value": 12961000,
        "cost": 12970000,
        "principal_amount": 13131000,
        "interest_rate": 0.1147,
        "basis_spread": 0.06,
        "reference_rate_type": "",
        "maturity_date": "2027-02-24",
        "pct_of_net_assets": 0.02,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    assert result.iloc[0]["issuer_name"] != "National Debt Relief"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_mm_apollo_institutional_hierarchy_extracts_debt_without_investment_type():
    raw = (
        "Commercial Services & Supplies Best Trash Bingo Group Buyer, Inc. "
        "First Lien Secured Debt - Term Loan S+475, 1.00% Floor Maturity Date 07/10/31"
    )
    df = pd.DataFrame([{
        "cik": "0002006758",
        "entity_name": "Middle Market Apollo Institutional Private Lending",
        "accession_number": "0001193125-26-214580",
        "form_type": "10-Q",
        "filing_date": "2026-05-08",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 9005000,
        "cost": 8958000,
        "principal_amount": 9050000,
        "interest_rate": 0.0475,
        "basis_spread": 0.0475,
        "reference_rate_type": "",
        "maturity_date": "2031-07-10",
        "pct_of_net_assets": 0.01,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Best Trash Bingo Group Buyer, Inc."
    assert row["instrument_description"].startswith("First Lien Secured Debt - Term Loan")
    assert "Commercial Services" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_mm_apollo_institutional_hierarchy_extracts_investment_type_debt():
    raw = (
        "Professional Services North Highland The North Highland Company LLC "
        "Investment Type First Lien Secured Debt - Revolver S+475, 0.75% Floor "
        "Maturity Date 12/20/30"
    )
    df = pd.DataFrame([{
        "cik": "0002006758",
        "entity_name": "Middle Market Apollo Institutional Private Lending",
        "accession_number": "0001193125-26-214580",
        "form_type": "10-Q",
        "filing_date": "2026-05-08",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 16000,
        "cost": 16000,
        "principal_amount": 17000,
        "interest_rate": 0.0475,
        "basis_spread": 0.0475,
        "reference_rate_type": "",
        "maturity_date": "2030-12-20",
        "pct_of_net_assets": 0.0001,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "North Highland The North Highland Company LLC"
    assert row["instrument_description"].startswith("First Lien Secured Debt - Revolver")
    assert "Investment Type" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_mm_apollo_institutional_hierarchy_extracts_equity_issuer_and_instrument():
    raw = "Pharmaceuticals PAI Pharma PAI Co-Investor FT Aggregator LLC Common Equity - Stock"
    df = pd.DataFrame([{
        "cik": "0002006758",
        "entity_name": "Middle Market Apollo Institutional Private Lending",
        "accession_number": "0001193125-26-214580",
        "form_type": "10-Q",
        "filing_date": "2026-05-08",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 42000,
        "cost": 50000,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.0001,
        "pik_rate": "",
        "shares_held": 50,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "PAI Pharma PAI Co-Investor FT Aggregator LLC"
    assert row["instrument_description"] == "Common Equity - Stock"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_ab_private_credit_investors_pipe_debt_extracts_issuer_and_instrument():
    raw = (
        "U.S. Corporate Debt | 1st Lien/Senior Secured Debt | "
        "Degreed, Inc| Software & Tech Services | Delayed Draw Term Loan| "
        "10.92% (S + 5.50%; 1.00% PIK; 1.00% Floor)| 05/29/2026"
    )
    df = pd.DataFrame([{
        "cik": "0001634452",
        "entity_name": "AB Private Credit Investors Corp",
        "accession_number": "0001634452-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 1000000,
        "cost": 990000,
        "principal_amount": 1000000,
        "interest_rate": 0.1092,
        "basis_spread": 0.055,
        "reference_rate_type": "",
        "maturity_date": "2026-05-29",
        "pct_of_net_assets": 0.01,
        "pik_rate": 0.01,
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Degreed, Inc"
    assert "Delayed Draw Term Loan" in row["instrument_description"]
    assert "U.S. Corporate Debt" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_ab_private_credit_investors_alternate_pipe_prefix_extracts_issuer():
    raw = (
        "U.S. 1st Lien/Senior Secured Debt | Gryphon Redwood Acquisition LLC | "
        "Software & Tech Services | Delayed Draw Term Loan | "
        "14.58% (S + 4.00%; 6.00% PIK; 1.00% Floor) | 09/16/2028"
    )
    df = pd.DataFrame([{
        "cik": "0001634452",
        "entity_name": "AB Private Credit Investors Corp",
        "accession_number": "0001634452-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 2000000,
        "cost": 1980000,
        "principal_amount": 2000000,
        "interest_rate": 0.1458,
        "basis_spread": 0.04,
        "reference_rate_type": "",
        "maturity_date": "2028-09-16",
        "pct_of_net_assets": 0.02,
        "pik_rate": 0.06,
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Gryphon Redwood Acquisition LLC"
    assert "Delayed Draw Term Loan" in row["instrument_description"]
    assert "Equity Investments" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_twenty_six_north_pipe_debt_extracts_issuer_and_instrument():
    raw = (
        "Debt Investments | Alert SRC Newco LLC |First Lien Senior Secured "
        "Delayed Draw Term Loan|Commercial Services & Supplies|SOFR + 5.000%|"
        "8.673%|12/11/2024|12/11/2030"
    )
    df = pd.DataFrame([{
        "cik": "0001950976",
        "entity_name": "26North BDC, Inc.",
        "accession_number": "0001950976-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 7142000,
        "cost": 7122000,
        "principal_amount": 7142000,
        "interest_rate": 0.08673,
        "basis_spread": 0.05,
        "reference_rate_type": "",
        "maturity_date": "2030-12-11",
        "pct_of_net_assets": 0.01,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Alert SRC Newco LLC"
    assert row["instrument_description"] == (
        "First Lien Senior Secured Delayed Draw Term Loan"
    )
    assert "Debt Investments" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_twenty_six_north_pipe_equity_extracts_issuer_and_instrument():
    raw = (
        "Equity|Great Dane Intermediate Holding I LLC |Preferred Equity| "
        "Software|14.00%|12/20/2025"
    )
    df = pd.DataFrame([{
        "cik": "0001950976",
        "entity_name": "26North BDC, Inc.",
        "accession_number": "0001950976-26-000001",
        "form_type": "10-Q",
        "filing_date": "2026-05-01",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 1000000,
        "cost": 900000,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.01,
        "pik_rate": "",
        "shares_held": 1000,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Great Dane Intermediate Holding I LLC"
    assert row["instrument_description"] == "Preferred Equity"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_scp_private_credit_income_pipe_debt_extracts_issuer_and_instrument():
    raw = (
        "Bank Debt/Senior Secured Loans | ACRES Commercial Mortgage LLC | "
        "Diversified Financial Services | S+705 | 1.00% | 11.38% | "
        "12/24/2021 | 8/21/2028"
    )
    df = pd.DataFrame([{
        "cik": "0001743415",
        "entity_name": "SCP Private Credit Income BDC LLC",
        "accession_number": "0000950170-24-042652",
        "form_type": "10-K",
        "filing_date": "2024-04-01",
        "report_date": "2023-12-31",
        "investment_identifier": raw,
        "fair_value": 3250000,
        "cost": 3300000,
        "principal_amount": 3350000,
        "interest_rate": 0.1138,
        "basis_spread": 0.0705,
        "reference_rate_type": "S",
        "maturity_date": "2028-08-21",
        "pct_of_net_assets": 0.01,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "ACRES Commercial Mortgage LLC"
    assert row["instrument_description"] == "Bank Debt/Senior Secured Loans"
    assert "Diversified Financial Services" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_scp_private_credit_income_dash_debt_extracts_issuer_and_instrument():
    raw = (
        "Bank Debt/Senior Secured Loans - 157.3% AMF Levered II, LLC "
        "Industry Diversified Financial Services Spread above Index S+705 "
        "Floor 1.00% Interest Rate 11.67% Acquisition Date 12/2021 "
        "Maturity Date 8/2028"
    )
    df = pd.DataFrame([{
        "cik": "0001743415",
        "entity_name": "SCP Private Credit Income BDC LLC",
        "accession_number": "0000950170-25-046748",
        "form_type": "10-K",
        "filing_date": "2025-03-28",
        "report_date": "2024-12-31",
        "investment_identifier": raw,
        "fair_value": 4400000,
        "cost": 4500000,
        "principal_amount": 4550000,
        "interest_rate": 0.1167,
        "basis_spread": 0.0705,
        "reference_rate_type": "S",
        "maturity_date": "2028-08-31",
        "pct_of_net_assets": 0.01,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "AMF Levered II, LLC"
    assert row["instrument_description"] == "Bank Debt/Senior Secured Loans"
    assert "Industry" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_scp_private_credit_income_equity_extracts_issuer_and_instrument():
    raw = (
        "Common Equity/Equity Interests/Warrants - Assertio Holdings, Inc. "
        "Common Stock Industry Pharmaceuticals Acquisition Date 07/2023"
    )
    df = pd.DataFrame([{
        "cik": "0001743415",
        "entity_name": "SCP Private Credit Income BDC LLC",
        "accession_number": "0000950170-25-046748",
        "form_type": "10-K",
        "filing_date": "2025-03-28",
        "report_date": "2024-12-31",
        "investment_identifier": raw,
        "fair_value": 390000,
        "cost": 400000,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.001,
        "pik_rate": "",
        "shares_held": 100,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Assertio Holdings, Inc."
    assert row["instrument_description"] == "Common Equity/Equity Interests/Warrants"
    assert "Industry" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_scp_private_credit_income_hierarchy_extract_is_cik_scoped():
    raw = (
        "Bank Debt/Senior Secured Loans - 157.3% AMF Levered II, LLC "
        "Industry Diversified Financial Services Spread above Index S+705 "
        "Floor 1.00% Interest Rate 11.67% Acquisition Date 12/2021 "
        "Maturity Date 8/2028"
    )
    df = pd.DataFrame([{
        "cik": "9999999999",
        "entity_name": "Not SCP Private Credit",
        "accession_number": "0000000000-25-000001",
        "form_type": "10-K",
        "filing_date": "2025-03-28",
        "report_date": "2024-12-31",
        "investment_identifier": raw,
        "fair_value": 4400000,
        "cost": 4500000,
        "principal_amount": 4550000,
        "interest_rate": 0.1167,
        "basis_spread": 0.0705,
        "reference_rate_type": "S",
        "maturity_date": "2028-08-31",
        "pct_of_net_assets": 0.01,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    assert result.iloc[0]["issuer_name"] != "AMF Levered II, LLC"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_senior_credit_investments_hierarchy_extracts_debt_issuer_and_instrument():
    raw = (
        "Non-Controlled/Non-Affiliated Portfolio Company Investments First "
        "Lien Debt Investments Health Care Technology Kona Buyer, LLC "
        "Investment Type First Lien Delayed Draw Term Loan Reference Rate "
        "and Spread S + 4.50% Maturity Date 7/23/2031"
    )
    df = pd.DataFrame([{
        "cik": "0001959568",
        "entity_name": "Senior Credit Investments, LLC",
        "accession_number": "0001193125-26-116346",
        "form_type": "10-K",
        "filing_date": "2026-03-20",
        "report_date": "2025-12-31",
        "investment_identifier": raw,
        "fair_value": 85000,
        "cost": 85000,
        "principal_amount": 86000,
        "interest_rate": "",
        "basis_spread": 0.045,
        "reference_rate_type": "",
        "maturity_date": "2031-07-23",
        "pct_of_net_assets": 0.001,
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Kona Buyer, LLC"
    assert row["instrument_description"] == "First Lien Delayed Draw Term Loan"
    assert "Portfolio Company Investments" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_senior_credit_investments_portfolio_company_extracts_lp_interest():
    raw = "Portfolio Company Firebird Co-Invest L.P. Investment Type L.P. Interest"
    df = pd.DataFrame([{
        "cik": "0001959568",
        "entity_name": "Senior Credit Investments, LLC",
        "accession_number": "0001193125-26-116346",
        "form_type": "10-K",
        "filing_date": "2026-03-20",
        "report_date": "2025-12-31",
        "investment_identifier": raw,
        "fair_value": 11000,
        "cost": 12000,
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": 0.0001,
        "pik_rate": "",
        "shares_held": 100,
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "Firebird Co-Invest L.P."
    assert row["instrument_description"] == "L.P. Interest"
    assert "Portfolio Company" not in row["issuer_name"]


@pytest.mark.slow
@pytest.mark.staging_sql
def test_nexpoint_capital_terminal_coupon_preferred_stock_survives_filter():
    raw = "Preferred Stocks | Financials | United Fidelity Bank FSB | 7.00%"
    df = pd.DataFrame([{
        "cik": "0001588272",
        "entity_name": "NexPoint Capital, Inc.  (NXPT)",
        "accession_number": "0001193125-26-223911",
        "form_type": "10-Q",
        "filing_date": "2026-05-15",
        "report_date": "2026-03-31",
        "investment_identifier": raw,
        "fair_value": 500000,
        "cost": 1000000,
        "principal_amount": 1000,
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": "",
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["issuer_name"] == "United Fidelity Bank FSB"
    assert row["instrument_description"].startswith("Preferred Stocks")
    assert row["asset_category"] == "EQUITY_PREFERRED"


@pytest.mark.slow
@pytest.mark.staging_sql
def test_nexpoint_capital_bare_preferred_category_is_not_output():
    df = pd.DataFrame([{
        "cik": "0001588272",
        "entity_name": "NexPoint Capital, Inc.  (NXPT)",
        "accession_number": "0001193125-26-223911",
        "form_type": "10-Q",
        "filing_date": "2026-05-15",
        "report_date": "2026-03-31",
        "investment_identifier": "Preferred Stocks",
        "fair_value": 12500000,
        "cost": "",
        "principal_amount": "",
        "interest_rate": "",
        "basis_spread": "",
        "reference_rate_type": "",
        "maturity_date": "",
        "pct_of_net_assets": "",
        "pik_rate": "",
        "shares_held": "",
        "unrealized_gain_loss": "",
        "dimensions_raw": "",
        "investment_type": "",
        "industry": "",
        "affiliation": "",
    }])

    result = _prepare_bdc(df)

    assert len(result) == 0
