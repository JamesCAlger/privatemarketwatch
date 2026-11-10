"""Tests for pipeline.oracle_checks -- comprehensive oracle check functions."""

import pandas as pd
import pytest

from pipeline.oracle_checks import (
    ALL_CHECK_IDS,
    CHECK_REGISTRY,
    CheckResult,
    _jaro_winkler_py,
    check_A01_subtotal_arithmetic,
    check_J01_position_key_stability,
    check_J03_fuzzy_fallback_rate,
    check_J05_lower_tier_match_consistency,
    check_J06_fuzzy_match_semantic_validation,
    check_J07_hard_gate_rejection_audit,
    check_J08_suspected_refinancing_detection,
    check_A04_gav_reconciliation,
    check_A07_pct_of_net_assets_sum,
    check_B01_leaf_completeness,
    check_B02_unique_position_keys,
    check_B07_single_accession_per_quarter,
    check_B08_comparative_period_exclusion,
    check_C01_debt_has_rate,
    check_C04_equity_has_shares,
    check_C05_no_rate_on_common_equity,
    check_C08_fv_required,
    check_D01_position_count_band,
    check_D02_fv_stability,
    check_D03_count_fv_divergence,
    check_D06_position_continuity,
    check_D07_rate_distribution_stability,
    check_E02_holdings_fv_vs_total_assets,
    check_E04_nav_per_share_sanity,
    check_E07_position_count_vs_filing,
    check_F01_interest_rate_range,
    check_F03_fair_value_sign,
    check_F07_null_fair_value,
    check_F08_duplicate_detection,
    check_F09_text_corruption,
    check_F11_shares_sign,
    check_F12_rate_scale_detection,
    check_G01_keyword_aggregate_detection,
    check_G02_arithmetic_subtotal_detection,
    check_G03_header_row_detection,
    check_H01_source_fact_coverage,
    check_H05_bdc_source_vs_unified_gap,
    check_I02_leaf_marker_accuracy,
    check_I06_non_private_market_exclusion,
    check_I08_segment_assertion_drift,
    check_I09_gics_issuer_name_detection,
    check_I10_instrument_subtype_coverage,
    check_I11_position_key_uniqueness_within_entity,
    check_J04_unique_position_id_per_report_date,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _source_detail(rows):
    """Build a source reconciliation detail DataFrame from row dicts."""
    defaults = {
        "status": "matched",
        "match_tier": "",
        "issue_severity": "",
        "residual_class": "reconciled",
        "blocking_issue": "false",
        "calibrated_status": "reconciled",
        "calibration_reason": "",
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "report_date": "2024-12-31",
        "period": "2024-12-31",
        "accession_number": "0001786108-25-000001",
        "form_type": "10-K",
        "filing_date": "2025-03-01",
        "context_id": "ctx",
        "source_row_id": "1",
        "output_row_id": "1",
        "raw_investment_identifier": "Acme Corp Term Loan",
        "normalized_investment_identifier": "acme corp term loan",
        "dimensions_raw": "",
        "concept_names": "InvestmentOwnedAtFairValue",
        "source_wrapper_disposition": "debt_position_leaf",
        "source_wrapper_rule_id": "TRINITY_DEBT_LEAF_V1",
        "source_wrapper_family": "debt",
        "source_wrapper_parent_key": "acme corp",
        "source_wrapper_position_key": "acme corp term loan",
        "source_wrapper_structured_leaf_key": "",
        "source_wrapper_investment_date_key": "",
        "source_wrapper_maturity_date_key": "",
        "source_wrapper_rate_key": "",
        "source_wrapper_signature_status": "pass",
        "source_wrapper_unparsed_remainder": "",
        "output_wrapper_disposition": "",
        "output_wrapper_rule_id": "",
        "output_wrapper_family": "",
        "output_wrapper_parent_key": "",
        "output_wrapper_position_key": "",
        "output_wrapper_structured_leaf_key": "",
        "output_wrapper_investment_date_key": "",
        "output_wrapper_maturity_date_key": "",
        "output_wrapper_rate_key": "",
        "output_wrapper_signature_status": "",
        "output_wrapper_unparsed_remainder": "",
        "source_fair_value": "5000000",
        "output_fair_value": "5000000",
        "source_cost": "",
        "output_cost": "",
        "source_principal_amount": "",
        "output_principal_amount": "",
        "source_shares_held": "",
        "output_shares_held": "",
        "source_interest_rate": "",
        "output_interest_rate": "",
        "source_basis_spread": "",
        "output_basis_spread": "",
        "source_pik_rate": "",
        "output_pik_rate": "",
        "mismatched_fields": "",
        "issuer_name": "",
        "instrument_description": "",
        "index_classification": "",
        "asset_category": "",
        "issuer_category": "",
        "evidence": "",
    }
    # each row its own XBRL context unless the test names one
    merged = [{**defaults, "context_id": f"ctx{i}", **row} for i, row in enumerate(rows)]
    return pd.DataFrame(merged)


def _holdings(rows):
    """Build a unified holdings DataFrame from row dicts."""
    defaults = {
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "report_date": "2024-12-31",
        "source": "bdc",
        "issuer_name": "Acme Corp",
        "instrument_description": "Senior Secured First Lien Term Loan",
        "fair_value": "5000000",
        "cost": "5000000",
        "interest_rate": "0.10",
        "basis_spread": "0.05",
        "shares_held": "",
        "principal_amount": "5000000",
        "pct_of_net_assets": "1.5",
        "index_classification": "senior_secured_debt",
        "asset_category": "debt",
        "issuer_category": "",
        "bdc_investment_identifier": "Acme Corp, Term Loan",
    }
    merged = [{**defaults, **row} for row in rows]
    return pd.DataFrame(merged)


def _fund_financials(rows):
    """Build a fund financials DataFrame from row dicts."""
    defaults = {
        "cik": "0001786108",
        "report_date": "2024-12-31",
        "investments_at_fair_value": "100000000",
        "total_assets": "120000000",
        "net_assets": "80000000",
        "nav_per_share": "15.0",
        "shares_outstanding": "5333333",
    }
    merged = [{**defaults, **row} for row in rows]
    return pd.DataFrame(merged)


# ===================================================================
# CATEGORY A TESTS
# ===================================================================

class TestA01SubtotalArithmetic:
    def test_pass_when_rollup_matches_children(self):
        detail = _source_detail([
            {
                "source_wrapper_disposition": "debt_issuer_rollup",
                "source_wrapper_parent_key": "acme corp",
                "source_wrapper_family": "debt",
                "source_fair_value": "10000000",
                "source_row_id": "parent",
                "output_row_id": "",
            },
            {
                "source_wrapper_disposition": "debt_position_leaf",
                "source_wrapper_parent_key": "acme corp term loan",
                "source_wrapper_family": "debt",
                "source_fair_value": "6000000",
                "source_row_id": "child1",
            },
            {
                "source_wrapper_disposition": "debt_position_leaf",
                "source_wrapper_parent_key": "acme corp revolver",
                "source_wrapper_family": "debt",
                "source_fair_value": "4000000",
                "source_row_id": "child2",
            },
        ])
        results = check_A01_subtotal_arithmetic(detail)
        assert any(r.status == "pass" for r in results)

    def test_fail_when_rollup_mismatches_children(self):
        detail = _source_detail([
            {
                "source_wrapper_disposition": "debt_issuer_rollup",
                "source_wrapper_parent_key": "acme corp",
                "source_wrapper_family": "debt",
                "source_fair_value": "20000000",
                "source_row_id": "parent",
                "output_row_id": "",
            },
            {
                "source_wrapper_disposition": "debt_position_leaf",
                "source_wrapper_parent_key": "acme corp term loan",
                "source_wrapper_family": "debt",
                "source_fair_value": "6000000",
                "source_row_id": "child1",
            },
        ])
        results = check_A01_subtotal_arithmetic(detail)
        assert any(r.status == "fail" for r in results)

    def test_skip_on_empty(self):
        results = check_A01_subtotal_arithmetic(pd.DataFrame())
        assert results[0].status == "skip"

    def test_a_subtotal_is_compared_with_the_rows_of_its_own_period(self):
        """Sixth Street: a filing carries the prior year-end rows and subtotal as well, on members
        with no period in their name. Each subtotal must meet its own period's rows."""
        def rollup(period, value):
            return {"source_wrapper_disposition": "debt_issuer_rollup", "source_wrapper_parent_key": "debt investments",
                    "source_wrapper_family": "debt", "source_fair_value": value, "period": period,
                    "report_date": "2023-12-31"}

        def leaf(period, value, name):
            return {"source_wrapper_disposition": "debt_position_leaf", "source_wrapper_parent_key": "debt investments " + name,
                    "source_wrapper_family": "debt", "source_fair_value": value, "period": period,
                    "report_date": "2023-12-31"}
        rows = [rollup("2023-12-31", "3000"), rollup("2022-12-31", "800000"),
                leaf("2023-12-31", "1000", "a"), leaf("2023-12-31", "2000", "b"), leaf("2022-12-31", "800000", "a")]
        assert all(r.status == "pass" for r in check_A01_subtotal_arithmetic(_source_detail(rows)))
        # a row missing from the current period still fails its subtotal
        short = [r for r in rows if not (r["period"] == "2023-12-31" and r["source_fair_value"] == "2000")]
        short[0] = rollup("2023-12-31", "3000000")
        short[2] = leaf("2023-12-31", "1000000", "a")
        assert any(r.status == "fail" for r in check_A01_subtotal_arithmetic(_source_detail(short)))

    def test_the_comparative_schedule_subtotal_is_not_checked_in_the_later_quarter(self):
        """Sixth Street 2023-03-31: the 10-Q prints the 2022-12-31 schedule too; its debt subtotal
        2,568,814 met comparative rows tagged on an older member format. Only the quarter's own
        subtotals are compared (owner ruling 2026-11-04)."""
        base = {"report_date": "2023-03-31", "source_wrapper_family": "debt"}
        rows = [
            {**base, "period": "2023-03-31", "source_wrapper_disposition": "debt_category_rollup",
             "source_wrapper_parent_key": "debt investments", "source_fair_value": "2707407000"},
            {**base, "period": "2023-03-31", "source_wrapper_disposition": "debt_position_leaf",
             "source_wrapper_parent_key": "debt investments a", "source_fair_value": "2707407000"},
            {**base, "period": "2022-12-31", "source_wrapper_disposition": "debt_category_rollup",
             "source_wrapper_parent_key": "debt investments", "source_fair_value": "2568814000"},
            {**base, "period": "2022-12-31", "source_wrapper_disposition": "debt_position_leaf",
             "source_wrapper_parent_key": "debt investments a", "source_fair_value": "2164017534"},
        ]
        results = check_A01_subtotal_arithmetic(_source_detail(rows))
        assert [r.status for r in results] == ["pass"]
        assert "1/1 rollups" in results[0].message

    @staticmethod
    def _tree(rollup_key, rollup_fv, leaves):
        rows = [{"source_wrapper_disposition": "mixed_category_rollup", "source_wrapper_family": "mixed",
                 "source_wrapper_parent_key": rollup_key, "source_fair_value": rollup_fv}]
        rows += [{"source_wrapper_disposition": "mixed_position_leaf", "source_wrapper_family": "mixed",
                  "source_wrapper_parent_key": key, "source_fair_value": fv} for key, fv in leaves]
        return check_A01_subtotal_arithmetic(_source_detail(rows))

    def test_issuer_name_text_containing_the_rollup_key_is_not_a_child(self):
        """Fidelity Private Credit 2023-06-30: the 'investments' total took as its only child the
        money fund 'Fidelity Investments Money Market ...'; BCP Special Opportunities: 'media'
        took 'Sovos Brands Intermediate' rows. Children must sit under the key in the path."""
        results = self._tree("investments", "1216949424", [
            ("affiliated mutual funds money market mutual funds fidelity investments money market", "1353796"),
        ])  # no child: nothing to compare
        assert [r.status for r in results] == ["pass"]
        assert results[0].detail is None or results[0].detail.empty
        results = self._tree("media", "9198672", [
            ("media nep group inc first lien term loan", "4088620"),
            ("media streamland media midco llc first lien term loan", "5110052"),
            ("food products sovos brands intermediate inc first lien term loan", "497840"),
            ("insurance alliant holdings intermediate llc first lien term loan", "2109604"),
        ])
        assert [r.status for r in results] == ["pass"]

    def test_a_member_that_repeats_its_heading_or_drops_a_space_is_still_a_child(self):
        results = self._tree("investments non controlled secured debt aerospace", "10000000", [
            ("investments non controlled secured debt aerospace acme term loan", "6000000"),
            ("investments investments non controlled secured debt aerospace bleriot term loan", "3000000"),
            ("investments non controlled secured debt aerospacered ventures term loan", "1000000"),
        ])
        assert [r.status for r in results] == ["pass"]

    def test_a_rollup_missing_a_child_under_its_key_still_fails(self):
        """False-positive guard: the structural match must not hide a real shortfall."""
        results = self._tree("media", "9198672", [
            ("media nep group inc first lien term loan", "4088620"),
            ("food products sovos brands intermediate inc first lien term loan", "5110052"),
        ])
        assert [r.status for r in results] == ["fail"]
        assert results[0].detail["child_sum_fv"].tolist() == [4088620.0]

    @staticmethod
    def _nexii(leaves):
        rows = [{"source_wrapper_disposition": "debt_issuer_rollup", "context_id": "C_rollup",
                 "source_wrapper_parent_key": "debt canada nexii", "source_fair_value": "14802000"}]
        rows += [{"source_wrapper_disposition": "debt_position_leaf", "context_id": ctx,
                  "source_wrapper_parent_key": "debt canada nexii", "source_fair_value": fv,
                  "source_row_id": row_id} for ctx, fv, row_id in leaves]
        return check_A01_subtotal_arithmetic(_source_detail(rows))

    def test_a_context_on_two_dimension_paths_is_one_child(self):
        """Trinity Capital 2023-03-31: each line's context appears twice in the detail (the second
        dimension path, source_row_id '#2'); Nexii 14,802 found children of 29,604."""
        results = self._nexii([("C_a", "10009000", "src:C_a"), ("C_a", "10009000", "src:C_a#2"),
                               ("C_b", "4793000", "src:C_b"), ("C_b", "4793000", "src:C_b#2"),
                               ("C_dur", "", "src:C_dur"), ("C_dur", "", "src:C_dur#2")])
        assert [r.status for r in results] == ["pass"]

    def test_two_lines_on_two_contexts_both_count_and_a_shortfall_still_fails(self):
        """False-positive guard: distinct contexts with the same key are distinct positions."""
        assert [r.status for r in self._nexii([("C_a", "10009000", "1"), ("C_b", "4793000", "2")])] == ["pass"]
        results = self._nexii([("C_a", "10009000", "src:C_a"), ("C_a", "10009000", "src:C_a#2")])
        assert [r.status for r in results] == ["fail"]
        assert results[0].detail["child_sum_fv"].tolist() == [10009000.0]

    def test_a_current_subtotal_that_does_not_tie_still_fails_beside_a_comparative_one(self):
        """False-positive guard: dropping comparative subtotals must not hide a current mismatch."""
        base = {"report_date": "2023-03-31", "source_wrapper_family": "debt"}
        rows = [
            {**base, "period": "2023-03-31", "source_wrapper_disposition": "debt_category_rollup",
             "source_wrapper_parent_key": "debt investments", "source_fair_value": "3000000000"},
            {**base, "period": "2023-03-31", "source_wrapper_disposition": "debt_position_leaf",
             "source_wrapper_parent_key": "debt investments a", "source_fair_value": "2707407000"},
            {**base, "period": "2022-12-31", "source_wrapper_disposition": "debt_category_rollup",
             "source_wrapper_parent_key": "debt investments", "source_fair_value": "2707407000"},
        ]
        results = check_A01_subtotal_arithmetic(_source_detail(rows))
        assert [r.status for r in results] == ["fail"]
        assert results[0].detail["rollup_fv"].tolist() == [3000000000.0]


class TestA01PrintedHeadingPairing:
    """Owner ruling 2026-11-10: a subtotal whose children by member key do not tie is paired with
    the published rows printed under its heading; it passes only on an exact tie."""

    ACC = "0001786108-25-000001"

    @classmethod
    def _case(cls, subtotal, leaves, extra_rollups=(), holdings_overrides=None):
        """leaves: (ctx, member key, source fv, printed heading, published fv or None for unpublished)."""
        rows = [{"source_wrapper_disposition": "debt_category_rollup", "source_wrapper_family": "debt",
                 "source_wrapper_parent_key": "debt investments", "source_fair_value": "999999999999",
                 "context_id": "C_sec"}]
        rows += [{"source_wrapper_disposition": "debt_industry_rollup", "source_wrapper_family": "debt",
                  "source_wrapper_parent_key": subtotal[0], "source_fair_value": subtotal[1], "context_id": "C_r"}]
        rows += [{"source_wrapper_disposition": "debt_industry_rollup", "source_wrapper_family": fam,
                  "source_wrapper_parent_key": key, "source_fair_value": fv, "context_id": f"C_x{i}"}
                 for i, (key, fv, fam) in enumerate(extra_rollups)]
        rows += [{"source_wrapper_disposition": f"{fam}_position_leaf", "source_wrapper_family": fam,
                  "source_wrapper_parent_key": key, "source_fair_value": fv, "context_id": ctx}
                 for ctx, key, fv, _, _, fam in leaves]
        holdings = _holdings([{"accession_number": cls.ACC, "src_context_id": ctx, "extracted_industry": heading,
                               "fair_value": pub, "accounting_record_class": "parent_schedule"}
                              for ctx, _, _, heading, pub, _ in leaves if pub is not None])
        if holdings_overrides:
            holdings = holdings_overrides(holdings)
        return _source_detail(rows), holdings

    @staticmethod
    def _sixth_street_education(kyriba_heading="Financial Services"):
        """Sixth Street 2023-09-30: Education 148,585 printed over Astra, Destiny and EMS Linq; the
        Kyriba revolver (1,415) is tagged on an Education member but printed under Financial Services."""
        return [
            ("C_astra", "debt investments education astra acquisition corp second lien loan", "34566000", "Education", "34566000", "debt"),
            ("C_destiny", "debt investments education destiny solutions first lien loan", "59103000", "Education", "59103000", "debt"),
            ("C_ems", "debt investments education ems linq inc first lien loan", "54916000", "Education", "54916000", "debt"),
            ("C_kyriba", "debt investments education kyriba corp first lien revolving loan", "1415000", kyriba_heading, "1415000", "debt"),
        ]

    def _run(self, subtotal_fv, leaves, key="debt investments education", extra_rollups=(), with_holdings=True,
             holdings_overrides=None):
        detail, holdings = self._case((key, subtotal_fv), leaves, extra_rollups, holdings_overrides)
        # the section rollup ('debt investments') is not under test: give it its exact child sum
        sec = detail["source_wrapper_parent_key"].eq("debt investments")
        leaf = (detail["source_wrapper_disposition"].str.endswith("_position_leaf")
                & detail["source_wrapper_parent_key"].str.startswith("debt investments "))
        detail.loc[sec, "source_fair_value"] = str(int(pd.to_numeric(detail.loc[leaf, "source_fair_value"]).sum()))
        results = check_A01_subtotal_arithmetic(detail, holdings if with_holdings else None)
        assert len(results) == 1
        return results[0]

    def test_subtotal_equal_to_the_rows_printed_under_its_heading_passes(self):
        r = self._run("148585000", self._sixth_street_education())
        assert r.status == "pass"
        assert "1 tie by printed heading" in r.message

    def test_without_printed_headings_the_member_key_shortfall_still_fails(self):
        r = self._run("148585000", self._sixth_street_education(), with_holdings=False)
        assert r.status == "fail"
        assert r.detail["child_sum_fv"].tolist() == [150000000.0]

    def test_near_miss_beyond_rounding_still_fails(self):
        """148,587 against printed rows of 148,585: inside A01's 0.5 pct band but not exact."""
        r = self._run("148587000", self._sixth_street_education())
        assert r.status == "fail"

    def test_a_printed_row_missing_from_the_published_rows_still_fails(self):
        """Real error: a row printed under the heading was not published (or published short)."""
        leaves = self._sixth_street_education()
        leaves[1] = leaves[1][:4] + (None, "debt")
        assert self._run("148585000", leaves).status == "fail"
        leaves = self._sixth_street_education()
        leaves[1] = leaves[1][:4] + ("50000000", "debt")
        assert self._run("148585000", leaves).status == "fail"

    def test_a_published_row_counted_twice_still_fails(self):
        def dup(h):
            return pd.concat([h, h[h["src_context_id"].eq("C_astra")].assign(src_context_id="C_astra2")], ignore_index=True)
        leaves = self._sixth_street_education() + [
            ("C_astra2", "debt investments education astra acquisition corp second lien loan", "", "Education", None, "debt")]
        assert self._run("148585000", leaves, holdings_overrides=dup).status == "fail"

    def test_rows_printed_under_the_heading_in_another_section_are_not_paired(self):
        """False-positive guard: Education is printed in the debt and the equity section; only the
        debt section's rows meet the debt subtotal."""
        equity = ("C_eq", "equity and other investments education ems linq inc class b units", "4763000", "Education", "4763000", "debt")
        assert self._run("148585000", self._sixth_street_education() + [equity]).status == "pass"
        # a subtotal that ties only with the equity row added still fails
        assert self._run("153348000", self._sixth_street_education() + [equity]).status == "fail"

    def test_a_heading_word_missing_from_the_subtotal_member_needs_a_unique_heading(self):
        """'debt investments specialty' (Retail missing): paired with 'Specialty Retail' when that is
        the one printed heading one word longer; ambiguous beside 'Specialty Chemicals'."""
        leaves = [
            ("C_a", "debt investments specialty les schwab term loan", "1248826", "Specialty Retail", "1248826", "debt"),
            ("C_b", "debt investments specialty woof holdings term loan", "633480", "Specialty Retail", "633480", "debt"),
            ("C_c", "debt investments specialty other co term loan", "500000", "Health Care", "500000", "debt"),
        ]
        assert self._run("1882306", leaves, key="debt investments specialty").status == "pass"
        ambiguous = leaves + [("C_d", "debt investments chemicals acme term loan", "700000", "Specialty Chemicals", "700000", "debt")]
        assert self._run("1882306", ambiguous, key="debt investments specialty").status == "fail"

    def test_heading_compares_without_case_punctuation_or_and(self):
        leaves = [
            ("C_a", "debt investments oil gas and consumable fuels laramie energy first lien loan", "26724000", "Oil, Gas & Consumable Fuels", "26724000", "debt"),
            ("C_b", "debt investments oil gas and consumable fuels trp assets first lien loan", "65000000", "Oil, Gas & Consumable Fuels", "65000000", "debt"),
            ("C_c", "debt investments oil gas and consumable fuels murchison first lien loan", "29388000", "Electric Utilities", "29388000", "debt"),
        ]
        assert self._run("91724000", leaves, key="debt investments oil gas and consumable fuels").status == "pass"

    def test_a_subtotal_whose_key_repeats_in_the_filing_is_not_paired(self):
        """Ambiguity: two subtotals on one member key (Sixth Street Lending Partners 2025-03-31)."""
        r = self._run("148585000", self._sixth_street_education(),
                      extra_rollups=[("debt investments education", "1021000", "debt")])
        assert r.status == "fail"
        assert 148585000.0 in r.detail["rollup_fv"].tolist()


class TestA04GavReconciliation:
    def test_pass_within_tolerance(self):
        holdings = _holdings([{"fair_value": "95000000"}])
        ff = _fund_financials([{"investments_at_fair_value": "100000000"}])
        results = check_A04_gav_reconciliation(holdings, ff)
        assert any(r.status == "pass" for r in results)

    def test_fail_outside_tolerance(self):
        holdings = _holdings([{"fair_value": "50000000"}])
        ff = _fund_financials([{"investments_at_fair_value": "100000000"}])
        results = check_A04_gav_reconciliation(holdings, ff)
        assert any(r.status == "fail" for r in results)

    def test_skip_no_financials(self):
        holdings = _holdings([{}])
        results = check_A04_gav_reconciliation(holdings, None)
        assert results[0].status == "skip"

    @pytest.mark.parametrize("holdings_fv, status", [
        ("1758911000", "pass"),   # Sixth Street 2023-06-30: equal to the printed total, 85.2 pct of total assets
        ("1960000000", "pass"),   # 95 pct, the usual share
        ("1630000000", "fail"),   # 79 pct: below the 85 pct floor (owner ruling, D-076)
        ("1000000000", "fail"),   # under half of total assets
        ("2200000000", "fail"),   # above total assets
    ])
    def test_total_assets_stand_in_with_a_one_sided_band(self, holdings_fv, status):
        holdings = _holdings([{"fair_value": holdings_fv}])
        ff = _fund_financials([{"investments_at_fair_value": "", "total_assets": "2063418000"}])
        results = check_A04_gav_reconciliation(holdings, ff)
        assert [r.status for r in results] == [status]
        assert "no investments figure filed" in results[0].message

    # Silver Point 2023-06-30 shape (D-2026-11-04 repair): schedule 847.4M plus a money-market
    # row 84.6M; the filed investments line is 847.4M and leaves the cash row out.
    @staticmethod
    def _with_cash(non_cash="847380000", cash="84630000"):
        return _holdings([{"fair_value": non_cash},
                          {"fair_value": cash, "asset_category": "CASH", "index_classification": "CASH",
                           "issuer_name": "First American Treasury Obligations Fund"}])

    def test_declared_ex_cash_filer_is_compared_without_its_cash_rows(self):
        ff = _fund_financials([{"investments_at_fair_value": "847380000"}])
        holdings = self._with_cash()
        old = check_A04_gav_reconciliation(holdings, ff, cash_outside_total=frozenset(),
                                           cash_inside_total=frozenset())
        assert [r.status for r in old] == ["fail"]
        new = check_A04_gav_reconciliation(holdings, ff, cash_outside_total=frozenset({"0001786108"}),
                                           cash_inside_total=frozenset())
        assert [r.status for r in new] == ["pass"]
        assert "wrapper says the investments total excludes them" in new[0].message

    def test_declared_ex_cash_filer_still_fails_a_short_schedule(self):
        """False-positive guard: ex cash the schedule is 20 pct under the filed line."""
        ff = _fund_financials([{"investments_at_fair_value": "847380000"}])
        holdings = self._with_cash(non_cash="677900000")
        results = check_A04_gav_reconciliation(holdings, ff, cash_outside_total=frozenset({"0001786108"}),
                                               cash_inside_total=frozenset())
        assert [r.status for r in results] == ["fail"]

    def test_undeclared_filer_detected_when_cash_rows_equal_filed_cash(self):
        """Silver Capital 2025-09-30 shape: cash row 127.6M equals the filed cash equivalents."""
        ff = _fund_financials([{"investments_at_fair_value": "334010000",
                                "cash_equivalents_at_fair_value": "127600000"}])
        holdings = self._with_cash(non_cash="334010000", cash="127600000")
        results = check_A04_gav_reconciliation(holdings, ff, cash_outside_total=frozenset(),
                                               cash_inside_total=frozenset())
        assert [r.status for r in results] == ["pass"]
        assert "equal the filed cash equivalents" in results[0].message

    @pytest.mark.parametrize("filed_cash, inside", [
        ("", frozenset()),                        # no filed cash figure: no evidence of the basis
        ("40000000", frozenset()),                # cash rows 127.6M do not equal the filed 40.0M
        ("117600000", frozenset()),               # 10M apart: 3 pct of the line, above the 0.5 pct band
        ("127600000", frozenset({"0001786108"})),  # wrapper says the line holds the cash rows
    ])
    def test_undeclared_filer_without_evidence_still_fails(self, filed_cash, inside):
        ff = _fund_financials([{"investments_at_fair_value": "334010000",
                                "cash_equivalents_at_fair_value": filed_cash}])
        holdings = self._with_cash(non_cash="334010000", cash="127600000")
        results = check_A04_gav_reconciliation(holdings, ff, cash_outside_total=frozenset(),
                                               cash_inside_total=inside)
        assert [r.status for r in results] == ["fail"]

    def test_cash_rows_inside_a_matching_line_are_not_removed(self):
        """A filer whose line holds the money-market fund: the total with cash ties and stays."""
        ff = _fund_financials([{"investments_at_fair_value": "931000000",
                                "cash_equivalents_at_fair_value": "84630000"}])
        results = check_A04_gav_reconciliation(self._with_cash(), ff, cash_outside_total=frozenset(),
                                               cash_inside_total=frozenset())
        assert [r.status for r in results] == ["pass"]
        assert "ex cash" not in results[0].message


class TestA07PctSum:
    def test_pass_normal_sum(self):
        rows = [{"pct_of_net_assets": str(i)} for i in range(1, 11)]
        holdings = _holdings(rows)
        results = check_A07_pct_of_net_assets_sum(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_extreme_sum(self):
        rows = [{"pct_of_net_assets": "100"} for _ in range(5)]
        holdings = _holdings(rows)
        results = check_A07_pct_of_net_assets_sum(holdings)
        assert any(r.status == "fail" for r in results)


# ===================================================================
# CATEGORY B TESTS
# ===================================================================

class TestB01LeafCompleteness:
    def test_pass_all_leaves_have_fv(self):
        detail = _source_detail([
            {"source_fair_value": "5000000"},
            {"source_fair_value": "3000000"},
        ])
        results = check_B01_leaf_completeness(detail)
        assert any(r.status == "pass" for r in results)

    def test_skip_on_empty(self):
        results = check_B01_leaf_completeness(pd.DataFrame())
        assert results[0].status == "skip"

    def test_a_date_only_twin_of_a_valued_context_is_not_a_leaf_without_value(self):
        twin = {"accession_number": "a1", "period": "2026-03-31", "report_date": "2026-03-31"}
        detail = _source_detail([
            {**twin, "raw_investment_identifier": "Acme first-lien loan", "source_fair_value": "5000000"},
            {**twin, "raw_investment_identifier": "Acme first-lien loan", "source_fair_value": ""},
            {**twin, "raw_investment_identifier": "Beta first-lien loan", "source_fair_value": "3000000"},
            {**twin, "raw_investment_identifier": "Beta first-lien loan", "source_fair_value": ""},
        ])
        results = check_B01_leaf_completeness(detail)
        assert [r.status for r in results] == ["pass"]
        assert "2/2 leaves" in results[0].message

    def test_a_context_without_value_and_without_a_valued_twin_still_counts(self):
        twin = {"accession_number": "a1", "period": "2026-03-31", "report_date": "2026-03-31"}
        detail = _source_detail([
            {**twin, "raw_investment_identifier": "Acme first-lien loan", "source_fair_value": "5000000"},
            {**twin, "raw_investment_identifier": "Hippo first-lien loan", "source_fair_value": ""},
            # the same member in another period is not a twin (and, being the comparative
            # schedule, is not counted at all)
            {"accession_number": "a1", "period": "2025-12-31", "report_date": "2026-03-31",
             "raw_investment_identifier": "Acme first-lien loan", "source_fair_value": ""},
        ])
        results = check_B01_leaf_completeness(detail)
        assert [r.status for r in results] == ["fail"]
        assert "1/2 leaves" in results[0].message

    def test_comparative_schedule_and_acquisition_date_only_contexts_are_not_counted(self):
        """Owner ruling 2026-11-04 (b01-leaves-without-value-are-the-comparative-schedule):
        Silver Capital 2023-09-30 counted 19 prior year-end contexts (undrawn and nil lines of the
        2022-12-31 schedule); Sixth Street counted contexts carrying only an acquisition date."""
        cur = {"accession_number": "a1", "period": "2023-09-30", "report_date": "2023-09-30"}
        comp = {**cur, "period": "2022-12-31"}
        rows = [{**cur, "raw_investment_identifier": f"Loan {i}", "source_fair_value": "1000000"} for i in range(20)]
        rows += [{**comp, "raw_investment_identifier": f"Old revolver {i}", "source_fair_value": ""} for i in range(19)]
        rows += [{**cur, "raw_investment_identifier": f"Acquired {i}", "source_fair_value": "",
                  "concept_names": "InvestmentAcquisitionDate"} for i in range(5)]
        results = check_B01_leaf_completeness(_source_detail(rows))
        assert [r.status for r in results] == ["pass"]
        assert "20/20 leaves" in results[0].message

    def test_current_leaves_without_value_fail_even_beside_a_valued_comparative_schedule(self):
        """False-positive guard (and the old dilution): 2 of 20 current lines without a value fail,
        however many valued comparative rows the filing also prints; a current context with an
        acquisition date and a rate is still a leaf."""
        cur = {"accession_number": "a1", "period": "2023-09-30", "report_date": "2023-09-30"}
        rows = [{**cur, "raw_investment_identifier": f"Loan {i}", "source_fair_value": "1000000"} for i in range(18)]
        rows += [{**cur, "raw_investment_identifier": "Unvalued A", "source_fair_value": "",
                  "concept_names": "InvestmentAcquisitionDate|InvestmentInterestRate"},
                 {**cur, "raw_investment_identifier": "Unvalued B", "source_fair_value": ""}]
        rows += [{**cur, "period": "2022-12-31", "raw_investment_identifier": f"Old {i}", "source_fair_value": "5"}
                 for i in range(40)]
        results = check_B01_leaf_completeness(_source_detail(rows))
        assert [r.status for r in results] == ["fail"]
        assert "18/20 leaves" in results[0].message


class TestB02UniquePositionKeys:
    def test_pass_no_dupes(self):
        holdings = _holdings([
            {"bdc_investment_identifier": "Acme Corp, Term Loan"},
            {"bdc_investment_identifier": "Beta Inc, Term Loan"},
        ])
        results = check_B02_unique_position_keys(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_duplicates(self):
        holdings = _holdings([
            {"bdc_investment_identifier": "Acme Corp, Term Loan"},
            {"bdc_investment_identifier": "Acme Corp, Term Loan"},
        ])
        results = check_B02_unique_position_keys(holdings)
        assert any(r.status == "fail" for r in results)

    def test_prefers_unified_position_key_when_present(self):
        holdings = _holdings([
            {"bdc_investment_identifier": "same raw id", "position_key": "acme corp term loan"},
            {"bdc_investment_identifier": "same raw id", "position_key": "beta inc term loan"},
        ])
        results = check_B02_unique_position_keys(holdings)
        assert any(r.status == "pass" for r in results)


class TestB07SingleAccession:
    def test_pass_single_accession(self):
        detail = _source_detail([
            {"accession_number": "0001786108-25-000001", "form_type": "10-K"},
        ])
        results = check_B07_single_accession_per_quarter(detail)
        assert any(r.status == "pass" for r in results)

    def test_warn_multiple_accessions(self):
        detail = _source_detail([
            {"accession_number": "0001786108-25-000001", "form_type": "10-K"},
            {"accession_number": "0001786108-25-000002", "form_type": "10-K"},
        ])
        results = check_B07_single_accession_per_quarter(detail)
        assert any(r.status == "warn" for r in results)


class TestB08ComparativePeriod:
    def test_pass_no_comparative(self):
        detail = _source_detail([{"period": "2024-12-31", "report_date": "2024-12-31"}])
        results = check_B08_comparative_period_exclusion(detail)
        assert results[0].status == "pass"

    def test_fail_blocking_comparative(self):
        detail = _source_detail([{
            "period": "2023-12-31",
            "report_date": "2024-12-31",
            "blocking_issue": "true",
        }])
        results = check_B08_comparative_period_exclusion(detail)
        assert results[0].status == "fail"


# ===================================================================
# CATEGORY C TESTS
# ===================================================================

class TestC01DebtHasRate:
    def test_pass_debt_with_rates(self):
        holdings = _holdings([
            {"index_classification": "senior_secured_debt", "interest_rate": "0.10"},
            {"index_classification": "senior_secured_debt", "basis_spread": "0.05"},
        ])
        results = check_C01_debt_has_rate(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_debt_without_rates(self):
        rows = [
            {"index_classification": "senior_secured_debt", "interest_rate": "", "basis_spread": ""}
            for _ in range(10)
        ]
        holdings = _holdings(rows)
        results = check_C01_debt_has_rate(holdings)
        assert any(r.status == "fail" for r in results)


class TestC04EquityHasShares:
    def test_pass_equity_with_shares(self):
        holdings = _holdings([
            {"index_classification": "equity", "shares_held": "1000",
             "asset_category": "equity", "instrument_description": "Common Stock"},
        ])
        results = check_C04_equity_has_shares(holdings)
        assert any(r.status == "pass" for r in results)


class TestC05NoRateOnCommonEquity:
    def test_pass_no_rate_on_common(self):
        holdings = _holdings([
            {"instrument_description": "Common Stock", "interest_rate": "0",
             "index_classification": "equity"},
        ])
        results = check_C05_no_rate_on_common_equity(holdings)
        assert results[0].status == "pass"

    def test_fail_rate_on_common(self):
        rows = [
            {"instrument_description": "Common Stock", "interest_rate": "0.08"}
            for _ in range(20)
        ]
        holdings = _holdings(rows)
        results = check_C05_no_rate_on_common_equity(holdings)
        assert results[0].status == "fail"


class TestC08FvRequired:
    def test_pass_all_have_fv(self):
        holdings = _holdings([{"fair_value": "5000000", "index_classification": "debt"}])
        results = check_C08_fv_required(holdings)
        assert results[0].status == "pass"


# ===================================================================
# CATEGORY D TESTS
# ===================================================================

class TestD01PositionCountBand:
    def test_pass_stable_counts(self):
        holdings = _holdings(
            [{"report_date": "2024-09-30"} for _ in range(10)]
            + [{"report_date": "2024-12-31"} for _ in range(12)]
        )
        results = check_D01_position_count_band(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_spike(self):
        holdings = _holdings(
            [{"report_date": "2024-09-30"} for _ in range(10)]
            + [{"report_date": "2024-12-31"} for _ in range(100)]
        )
        results = check_D01_position_count_band(holdings)
        assert any(r.status == "fail" for r in results)


class TestD02FvStability:
    def test_pass_stable_fv(self):
        holdings = _holdings([
            {"report_date": "2024-09-30", "fair_value": "5000000"},
            {"report_date": "2024-12-31", "fair_value": "5500000"},
        ])
        results = check_D02_fv_stability(holdings)
        assert any(r.status == "pass" for r in results)


class TestD03CountFvDivergence:
    def test_pass_no_divergence(self):
        holdings = _holdings([
            {"report_date": "2024-09-30", "fair_value": "5000000"},
            {"report_date": "2024-12-31", "fair_value": "5000000"},
        ])
        results = check_D03_count_fv_divergence(holdings)
        # Should pass since count ratio is 1:1
        assert all(r.status in ("pass", "skip") for r in results)


class TestD06PositionContinuity:
    def test_pass_high_continuity(self):
        holdings = _holdings([
            {"report_date": "2024-09-30", "issuer_name": "Acme Corp"},
            {"report_date": "2024-09-30", "issuer_name": "Beta Inc"},
            {"report_date": "2024-12-31", "issuer_name": "Acme Corp"},
            {"report_date": "2024-12-31", "issuer_name": "Beta Inc"},
        ])
        results = check_D06_position_continuity(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_low_continuity(self):
        holdings = _holdings([
            {"report_date": "2024-09-30", "issuer_name": "Acme Corp"},
            {"report_date": "2024-09-30", "issuer_name": "Beta Inc"},
            {"report_date": "2024-12-31", "issuer_name": "Gamma LLC"},
            {"report_date": "2024-12-31", "issuer_name": "Delta Holdings"},
        ])
        results = check_D06_position_continuity(holdings)
        assert any(r.status == "fail" for r in results)


class TestD07RateStability:
    def test_skip_no_rate_data(self):
        holdings = _holdings([{"interest_rate": ""}])
        results = check_D07_rate_distribution_stability(holdings)
        assert results[0].status == "skip"


# ===================================================================
# CATEGORY E TESTS
# ===================================================================

class TestE02HoldingsFvVsTotalAssets:
    def test_pass_holdings_below_total_assets(self):
        holdings = _holdings([{"fair_value": "100000000"}])
        ff = _fund_financials([{"total_assets": "120000000"}])
        results = check_E02_holdings_fv_vs_total_assets(holdings, ff)
        assert any(r.status == "pass" for r in results)

    def test_fail_holdings_above_total_assets(self):
        holdings = _holdings([{"fair_value": "200000000"}])
        ff = _fund_financials([{"total_assets": "120000000"}])
        results = check_E02_holdings_fv_vs_total_assets(holdings, ff)
        assert any(r.status == "fail" for r in results)


class TestE04NavPerShareSanity:
    def test_pass_consistent(self):
        ff = _fund_financials([{
            "nav_per_share": "15.0",
            "shares_outstanding": "5333333",
            "net_assets": "80000000",
        }])
        results = check_E04_nav_per_share_sanity(ff)
        assert any(r.status == "pass" for r in results)

    def test_fail_inconsistent(self):
        ff = _fund_financials([{
            "nav_per_share": "15.0",
            "shares_outstanding": "5333333",
            "net_assets": "200000000",
        }])
        results = check_E04_nav_per_share_sanity(ff)
        assert any(r.status == "fail" for r in results)


class TestE07PositionCountVsFiling:
    def test_pass_close_counts(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf", "source_row_id": str(i)}
            for i in range(10)
        ])
        holdings = _holdings([{} for _ in range(10)])
        results = check_E07_position_count_vs_filing(detail, holdings)
        assert any(r.status == "pass" for r in results)


# ===================================================================
# CATEGORY F TESTS
# ===================================================================

class TestF01InterestRateRange:
    def test_pass_normal_rates(self):
        holdings = _holdings([
            {"interest_rate": "0.08"},
            {"interest_rate": "0.12"},
        ])
        results = check_F01_interest_rate_range(holdings)
        assert results[0].status == "pass"

    def test_warn_high_rates(self):
        holdings = _holdings([
            {"interest_rate": "500"},  # Way out of range
        ])
        results = check_F01_interest_rate_range(holdings)
        assert results[0].status in ("warn", "fail")


class TestF03FairValueSign:
    def test_pass_all_positive(self):
        holdings = _holdings([
            {"fair_value": "5000000"},
            {"fair_value": "3000000"},
        ])
        results = check_F03_fair_value_sign(holdings)
        assert results[0].status == "pass"

    def test_fail_many_negative(self):
        rows = [{"fair_value": "-1000000"} for _ in range(10)]
        holdings = _holdings(rows)
        results = check_F03_fair_value_sign(holdings)
        assert results[0].status == "fail"


class TestF07NullFairValue:
    def test_pass_no_nulls(self):
        holdings = _holdings([{"fair_value": "5000000"}])
        results = check_F07_null_fair_value(holdings)
        assert results[0].status == "pass"


class TestF08DuplicateDetection:
    def test_pass_no_dupes(self):
        holdings = _holdings([
            {"issuer_name": "Acme Corp", "fair_value": "5000000"},
            {"issuer_name": "Beta Inc", "fair_value": "3000000"},
        ])
        results = check_F08_duplicate_detection(holdings)
        assert results[0].status == "pass"

    def test_warn_dupes(self):
        holdings = _holdings([
            {"issuer_name": "Acme Corp", "instrument_description": "Term Loan",
             "fair_value": "5000000"},
            {"issuer_name": "Acme Corp", "instrument_description": "Term Loan",
             "fair_value": "5000000"},
        ])
        results = check_F08_duplicate_detection(holdings)
        assert results[0].status == "warn"


class TestF09TextCorruption:
    def test_pass_clean_text(self):
        holdings = _holdings([{"issuer_name": "Acme Corp"}])
        results = check_F09_text_corruption(holdings)
        assert results[0].status == "pass"


class TestF11SharesSign:
    def test_pass_positive_shares(self):
        holdings = _holdings([{"shares_held": "1000"}])
        results = check_F11_shares_sign(holdings)
        assert results[0].status == "pass"

    def test_warn_negative_shares(self):
        holdings = _holdings([{"shares_held": "-1000"}])
        results = check_F11_shares_sign(holdings)
        assert results[0].status == "warn"


class TestF12RateScale:
    def test_pass_normal_scale(self):
        holdings = _holdings([{"interest_rate": "8.5"}])
        results = check_F12_rate_scale_detection(holdings)
        assert results[0].status == "pass"


# ===================================================================
# CATEGORY G TESTS
# ===================================================================

class TestG01KeywordAggregate:
    def test_pass_no_aggregates(self):
        holdings = _holdings([
            {"issuer_name": "Acme Corp", "instrument_description": "Term Loan"},
        ])
        results = check_G01_keyword_aggregate_detection(holdings)
        assert results[0].status == "pass"

    def test_warn_aggregate_leaked(self):
        holdings = _holdings([
            {"issuer_name": "Total investments at fair value"},
        ])
        results = check_G01_keyword_aggregate_detection(holdings)
        assert results[0].status == "warn"


class TestG02ArithmeticSubtotal:
    def test_pass_no_subtotals(self):
        holdings = _holdings([
            {"fair_value": "5000000"},
            {"fair_value": "3000000"},
            {"fair_value": "7000000"},
        ])
        results = check_G02_arithmetic_subtotal_detection(holdings)
        assert results[0].status == "pass"

    def test_warn_subtotal_detected(self):
        # Row 0 FV = sum of rows 1+2
        holdings = _holdings([
            {"fair_value": "8000000"},
            {"fair_value": "5000000"},
            {"fair_value": "3000000"},
        ])
        results = check_G02_arithmetic_subtotal_detection(holdings)
        assert results[0].status == "warn"


class TestG03HeaderRow:
    def test_pass_no_headers(self):
        holdings = _holdings([{"fair_value": "5000000"}])
        results = check_G03_header_row_detection(holdings)
        assert results[0].status == "pass"


# ===================================================================
# CATEGORY H TESTS
# ===================================================================

class TestH01SourceFactCoverage:
    def test_pass_high_coverage(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf",
             "source_fair_value": "5000000",
             "output_row_id": "1"},
            {"source_wrapper_disposition": "debt_position_leaf",
             "source_fair_value": "3000000",
             "status": "matched"},
        ])
        holdings = _holdings([{}])
        results = check_H01_source_fact_coverage(detail, holdings)
        assert results[0].status == "pass"


class TestH05BdcSourceVsUnifiedGap:
    def test_pass_no_source_only(self):
        detail = _source_detail([{"status": "matched"}])
        results = check_H05_bdc_source_vs_unified_gap(detail)
        assert results[0].status == "pass"

    def test_fail_blocking_source_only(self):
        detail = _source_detail([{
            "status": "missing_from_pipeline",
            "blocking_issue": "true",
        }])
        results = check_H05_bdc_source_vs_unified_gap(detail)
        assert results[0].status in ("fail", "warn")


# ===================================================================
# CATEGORY I TESTS
# ===================================================================

class TestI02LeafMarkerAccuracy:
    def test_pass_leaves_have_fv(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf", "source_fair_value": "5000000"},
        ])
        results = check_I02_leaf_marker_accuracy(detail)
        assert results[0].status == "pass"


class TestI06NonPrivateMarketExclusion:
    def test_pass_npm_matches_pattern(self):
        detail = _source_detail([{
            "source_wrapper_disposition": "non_private_market",
            "raw_investment_identifier": "Cash and money market funds",
        }])
        results = check_I06_non_private_market_exclusion(detail)
        assert results[0].status == "pass"


class TestI08SegmentAssertionDrift:
    def test_pass_correct_segments(self):
        """Segment assertion passes when pattern matches."""
        detail = _source_detail([{
            "source_wrapper_disposition": "debt_position_leaf",
            "cik": "0001950803",
            "raw_investment_identifier": (
                "Non-Controlled Debt | First Lien | Software | "
                "Acme Corp, LLC Term Loan | 3M SOFR + 5.50% | 12.0% | 3/31/2029"
            ),
        }])
        assertions = {
            "0001950803": [
                {
                    "segment_index": 3,
                    "field_name": "industry",
                    "expected_pattern": "gics_sector_like",
                    "segment_count": 7,
                    "min_prevalence": 0.80,
                    "description": "Segment 3 = GICS industry",
                },
            ]
        }
        results = check_I08_segment_assertion_drift(detail, wrapper_specs=assertions)
        assert any(r.status == "pass" for r in results)

    def test_warn_wrong_segment_content(self):
        """Segment assertion warns when content doesn't match expected pattern."""
        detail = _source_detail([{
            "source_wrapper_disposition": "debt_position_leaf",
            "cik": "0001950803",
            "raw_investment_identifier": (
                "Non-Controlled Debt | First Lien | Acme Corp | "
                "Software | 3M SOFR + 5.50% | 12.0% | 3/31/2029"
            ),
        }])
        # Asserting segment 3 should be industry, but it's actually a company name
        assertions = {
            "0001950803": [
                {
                    "segment_index": 3,
                    "field_name": "industry",
                    "expected_pattern": "gics_sector_like",
                    "segment_count": 7,
                    "min_prevalence": 0.80,
                    "description": "Segment 3 = GICS industry",
                },
            ]
        }
        results = check_I08_segment_assertion_drift(detail, wrapper_specs=assertions)
        assert any(r.status == "warn" for r in results)

    def test_skip_when_no_specs(self):
        detail = _source_detail([{
            "source_wrapper_disposition": "debt_position_leaf",
        }])
        results = check_I08_segment_assertion_drift(detail, wrapper_specs={})
        assert results[0].status == "skip"


class TestI09GicsIssuerNameDetection:
    def test_pass_no_gics_in_issuer(self):
        """Normal issuer names should not trigger GICS detection."""
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp, LLC"},
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Beta Holdings Inc."},
        ])
        results = check_I09_gics_issuer_name_detection(detail)
        assert results[0].status == "pass"

    def test_warn_gics_in_issuer(self):
        """GICS labels as issuer_name should be flagged."""
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf",
             "cik": "0001111111", "report_date": "2024-12-31",
             "issuer_name": "Software"},
            {"source_wrapper_disposition": "debt_position_leaf",
             "cik": "0001111111", "report_date": "2024-12-31",
             "issuer_name": "Insurance"},
            {"source_wrapper_disposition": "debt_position_leaf",
             "cik": "0001111111", "report_date": "2024-12-31",
             "issuer_name": "Acme Corp"},
        ])
        results = check_I09_gics_issuer_name_detection(detail)
        # 2 out of 3 have GICS names = 66.7% > 5% threshold
        assert any(r.status in ("warn", "fail") for r in results)

    def test_skip_empty(self):
        results = check_I09_gics_issuer_name_detection(pd.DataFrame())
        assert results[0].status == "skip"


class TestI10InstrumentSubtypeCoverage:
    def test_pass_distinct_instruments(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp", "instrument_description": "Term Loan A"},
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp", "instrument_description": "Revolver"},
        ])
        results = check_I10_instrument_subtype_coverage(detail)
        assert results[0].status == "pass"

    def test_warn_identical_instruments(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp", "instrument_description": "Term Loan"},
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp", "instrument_description": "Term Loan"},
        ])
        results = check_I10_instrument_subtype_coverage(detail)
        # 1 out of 1 multi-position group has identical instruments = 100% > 50%
        assert results[0].status == "warn"

    def test_skip_no_multi_groups(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp", "instrument_description": "Term Loan"},
        ])
        results = check_I10_instrument_subtype_coverage(detail)
        assert results[0].status == "skip"


class TestI11PositionKeyUniquenessWithinEntity:
    def test_pass_unique_keys(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp", "position_key": "acme term loan a"},
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp", "position_key": "acme revolver"},
        ])
        results = check_I11_position_key_uniqueness_within_entity(detail)
        assert results[0].status == "pass"

    def test_warn_near_duplicate_keys(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp", "position_key": "acme term loan 1"},
            {"source_wrapper_disposition": "debt_position_leaf",
             "issuer_name": "Acme Corp", "position_key": "acme term loan 2"},
        ])
        results = check_I11_position_key_uniqueness_within_entity(detail)
        # Keys differ only by trailing digit -> near-duplicate
        assert results[0].status == "warn"

    def test_skip_empty(self):
        results = check_I11_position_key_uniqueness_within_entity(pd.DataFrame())
        assert results[0].status == "skip"


# ===================================================================
# REGISTRY TESTS
# ===================================================================

class TestCheckRegistry:
    def test_all_checks_registered(self):
        assert len(CHECK_REGISTRY) >= 41

    def test_all_check_ids_sorted(self):
        assert ALL_CHECK_IDS == sorted(ALL_CHECK_IDS)

    def test_all_checks_return_list(self):
        """Each check function should return a list when given empty DataFrames."""
        for check_id, (func, _) in CHECK_REGISTRY.items():
            import inspect
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            kwargs = {}
            for p in params:
                if "df" in p:
                    kwargs[p] = pd.DataFrame()
            try:
                result = func(**kwargs)
                assert isinstance(result, list), f"{check_id} did not return list"
                for r in result:
                    assert isinstance(r, CheckResult), f"{check_id} did not return CheckResult"
            except TypeError:
                pass  # Some checks need non-None args


class TestCheckResult:
    def test_to_dict(self):
        result = CheckResult(
            check_id="A01",
            scope="global",
            status="pass",
            metric_value=1.0,
            threshold=0.95,
            residual_rows=0,
            residual_fv=0,
            message="All good",
        )
        d = result.to_dict()
        assert d["check_id"] == "A01"
        assert d["status"] == "pass"
        assert d["detail_rows"] == 0


# ---------------------------------------------------------------------------
# Matches fixture
# ---------------------------------------------------------------------------

def _matches(rows):
    """Build a position_matches DataFrame from row dicts."""
    defaults = {
        "cik": "0001287750",
        "entity_name": "ARES CAPITAL CORP",
        "source": "bdc",
        "match_method": "B1b_position_key",
        "match_key": "acme corp term loan",
        "match_score": "1.0",
    }
    merged = [{**defaults, **row} for row in rows]
    return pd.DataFrame(merged)


# ===================================================================
# CATEGORY J TESTS: Position Matching Quality
# ===================================================================

class TestJ04UniquePositionIdPerReportDate:
    """Tests for J04: no duplicate position_id within one CIK/source/date."""

    def test_pass_unique_position_ids(self):
        holdings = _holdings([
            {"position_id": "POS-00000001", "issuer_name": "Acme Corp"},
            {"position_id": "POS-00000002", "issuer_name": "Beta Inc"},
        ])
        results = check_J04_unique_position_id_per_report_date(holdings)
        assert results[0].status == "pass"

    def test_fail_duplicate_position_id_same_date(self):
        holdings = _holdings([
            {"position_id": "POS-00000001", "issuer_name": "Acme Corp"},
            {"position_id": "POS-00000001", "issuer_name": "Beta Inc"},
        ])
        results = check_J04_unique_position_id_per_report_date(holdings)
        assert results[0].status == "fail"
        assert results[0].metric_value == 1


class TestJ01PositionKeyStability:
    """Tests for J01: B1b rate for wrapped CIKs."""

    def test_skip_when_no_matches(self):
        results = check_J01_position_key_stability(None)
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_skip_when_empty(self):
        results = check_J01_position_key_stability(pd.DataFrame())
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_pass_high_b1b_rate(self, monkeypatch):
        """Wrapped CIK with >70% B1b among non-A/B1 matches -> pass."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            # 8 B1b matches
            *[{"match_method": "B1b_position_key"}] * 8,
            # 2 B2 matches (below threshold)
            *[{"match_method": "B2_exact_name"}] * 2,
            # 5 A matches (excluded from denominator)
            *[{"match_method": "A_within_filing"}] * 5,
        ])
        results = check_J01_position_key_stability(df)
        passed = [r for r in results if r.cik == "0001287750"]
        assert len(passed) == 1
        assert passed[0].status == "pass"
        assert passed[0].metric_value == pytest.approx(0.8)  # 8/10

    def test_fail_low_b1b_rate(self, monkeypatch):
        """Wrapped CIK with <70% B1b among non-A/B1 matches -> fail."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001572694"},
        )
        df = _matches([
            # 1 B1b, 9 D_fuzzy
            {"cik": "0001572694", "match_method": "B1b_position_key"},
            *[{"cik": "0001572694", "match_method": "D_fuzzy"}] * 9,
        ])
        results = check_J01_position_key_stability(df)
        failed = [r for r in results if r.cik == "0001572694"]
        assert len(failed) == 1
        assert failed[0].status == "fail"
        assert failed[0].metric_value == pytest.approx(0.1)  # 1/10
        assert not failed[0].detail.empty  # tier breakdown provided

    def test_skip_all_tier_a(self, monkeypatch):
        """Wrapped CIK with only A matches -> skip (key not tested)."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            *[{"match_method": "A_within_filing"}] * 10,
        ])
        results = check_J01_position_key_stability(df)
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_non_wrapped_cik_excluded(self, monkeypatch):
        """Non-wrapped CIKs should not be evaluated."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},  # only Ares
        )
        df = _matches([
            # Non-wrapped CIK with bad B1b rate
            *[{"cik": "0009999999", "match_method": "D_fuzzy"}] * 10,
        ])
        results = check_J01_position_key_stability(df)
        # Should skip -- no matches for the wrapped CIK
        assert all(r.status == "skip" for r in results)


class TestJ03FuzzyFallbackRate:
    """Tests for J03: fuzzy match rate for wrapped CIKs."""

    def test_skip_when_no_matches(self):
        results = check_J03_fuzzy_fallback_rate(None)
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_pass_low_fuzzy(self, monkeypatch):
        """Wrapped CIK with <10% fuzzy -> pass."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            *[{"match_method": "A_within_filing"}] * 50,
            *[{"match_method": "B1b_position_key"}] * 40,
            *[{"match_method": "B2_exact_name"}] * 5,
            *[{"match_method": "D_fuzzy"}] * 5,  # 5% fuzzy
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        passed = [r for r in results if r.cik == "0001287750"]
        assert len(passed) == 1
        assert passed[0].status == "pass"
        assert passed[0].metric_value == pytest.approx(0.05)

    def test_fail_high_fuzzy(self, monkeypatch):
        """Wrapped CIK with >10% fuzzy -> fail."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001572694"},
        )
        df = _matches([
            *[{"cik": "0001572694", "match_method": "B1b_position_key"}] * 2,
            *[{"cik": "0001572694", "match_method": "D_fuzzy"}] * 18,  # 90%
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        failed = [r for r in results if r.cik == "0001572694"]
        assert len(failed) == 1
        assert failed[0].status == "fail"
        assert failed[0].metric_value == pytest.approx(0.9)
        assert not failed[0].detail.empty

    def test_pass_zero_fuzzy(self, monkeypatch):
        """Wrapped CIK with no fuzzy at all -> pass."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            *[{"match_method": "A_within_filing"}] * 10,
            *[{"match_method": "B1b_position_key"}] * 10,
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        passed = [r for r in results if r.cik == "0001287750"]
        assert len(passed) == 1
        assert passed[0].status == "pass"
        assert passed[0].metric_value == 0.0

    def test_boundary_exactly_10_pct(self, monkeypatch):
        """Exactly 10% fuzzy is at the threshold -> pass (<=)."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            *[{"match_method": "B1b_position_key"}] * 9,
            *[{"match_method": "D_fuzzy"}] * 1,  # exactly 10%
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        passed = [r for r in results if r.cik == "0001287750"]
        assert len(passed) == 1
        assert passed[0].status == "pass"

    def test_detail_includes_match_keys(self, monkeypatch):
        """Failed check should include fuzzy match keys for debugging."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001572694"},
        )
        df = _matches([
            {"cik": "0001572694", "match_method": "D_fuzzy",
             "match_key": "lithium technologies inc"},
            *[{"cik": "0001572694", "match_method": "D_fuzzy",
               "match_key": "atx networks corp"}] * 4,
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        failed = [r for r in results if r.cik == "0001572694"]
        assert len(failed) == 1
        assert "match_key" in failed[0].detail.columns


# ===================================================================
# J05: Lower-Tier Match Pair Consistency
# ===================================================================

class TestJ05LowerTierMatchConsistency:
    """Tests for J05: attribute discontinuity flags on B2/C/D/E matches."""

    def test_skip_when_no_matches(self):
        results = check_J05_lower_tier_match_consistency(None)
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_skip_when_empty(self):
        results = check_J05_lower_tier_match_consistency(pd.DataFrame())
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_pass_correct_matches(self, monkeypatch):
        """Matches with consistent attributes -> pass (no suspect)."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            {"match_method": "B2_exact_name",
             "begin_fair_value": "1000000", "end_fair_value": "1050000",
             "begin_interest_rate": "8.5", "end_interest_rate": "8.5",
             "begin_principal_amount": "1000000", "end_principal_amount": "1000000"},
            {"match_method": "C_normalized_name",
             "begin_fair_value": "500000", "end_fair_value": "480000",
             "begin_interest_rate": "9.0", "end_interest_rate": "9.5",
             "begin_principal_amount": "500000", "end_principal_amount": "500000"},
        ])
        results = check_J05_lower_tier_match_consistency(df)
        cik_results = [r for r in results if r.cik == "0001287750"]
        assert len(cik_results) == 1
        assert cik_results[0].status == "pass"

    def test_warn_wrong_tranche(self, monkeypatch):
        """Match with extreme FV ratio + rate discontinuity -> suspect."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        # All 3 matches have 2+ flags -> 100% suspect rate -> warn
        df = _matches([
            {"match_method": "B2_exact_name",
             "begin_fair_value": "10000000", "end_fair_value": "500000",
             "begin_interest_rate": "8.5", "end_interest_rate": "15.0",
             "begin_principal_amount": "10000000", "end_principal_amount": "500000"},
            {"match_method": "D_fuzzy",
             "begin_fair_value": "20000000", "end_fair_value": "100000",
             "begin_interest_rate": "5.0", "end_interest_rate": "12.0",
             "begin_principal_amount": "20000000", "end_principal_amount": "100000"},
            {"match_method": "C_normalized_name",
             "begin_fair_value": "5000000", "end_fair_value": "200000",
             "begin_interest_rate": "7.0", "end_interest_rate": "14.0",
             "begin_principal_amount": "5000000", "end_principal_amount": "200000"},
        ])
        results = check_J05_lower_tier_match_consistency(df)
        cik_results = [r for r in results if r.cik == "0001287750"]
        assert len(cik_results) == 1
        assert cik_results[0].status == "warn"
        assert cik_results[0].metric_value > 0.05

    def test_single_flag_not_suspect(self, monkeypatch):
        """A match with only 1 flag should NOT be suspect."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            # Only rate discontinuity (1 flag) -- not suspect
            {"match_method": "B2_exact_name",
             "begin_fair_value": "1000000", "end_fair_value": "1050000",
             "begin_interest_rate": "5.0", "end_interest_rate": "12.0",
             "begin_principal_amount": "1000000", "end_principal_amount": "1000000"},
        ])
        results = check_J05_lower_tier_match_consistency(df)
        cik_results = [r for r in results if r.cik == "0001287750"]
        assert len(cik_results) == 1
        assert cik_results[0].status == "pass"

    def test_a_and_b1b_tiers_excluded(self, monkeypatch):
        """A and B1b matches should not be evaluated by J05."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            # These have extreme discontinuities but should be excluded
            {"match_method": "A_within_filing",
             "begin_fair_value": "10000000", "end_fair_value": "100",
             "begin_interest_rate": "5.0", "end_interest_rate": "20.0",
             "begin_principal_amount": "10000000", "end_principal_amount": "100"},
            {"match_method": "B1b_position_key",
             "begin_fair_value": "10000000", "end_fair_value": "100",
             "begin_interest_rate": "5.0", "end_interest_rate": "20.0",
             "begin_principal_amount": "10000000", "end_principal_amount": "100"},
        ])
        results = check_J05_lower_tier_match_consistency(df)
        # Should skip -- no lower-tier matches
        assert all(r.status == "skip" for r in results)

    def test_zero_fv_not_flagged(self, monkeypatch):
        """Zero FV should not trigger fv_ratio flag."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            {"match_method": "B2_exact_name",
             "begin_fair_value": "0", "end_fair_value": "1000000",
             "begin_interest_rate": "8.5", "end_interest_rate": "8.5",
             "begin_principal_amount": "0", "end_principal_amount": "1000000"},
        ])
        results = check_J05_lower_tier_match_consistency(df)
        cik_results = [r for r in results if r.cik == "0001287750"]
        assert len(cik_results) == 1
        assert cik_results[0].status == "pass"


# ===================================================================
# J06: Fuzzy Match Semantic Validation
# ===================================================================

class TestJ06FuzzyMatchSemanticValidation:
    """Tests for J06: name divergence and classification flip on D/E matches."""

    def test_skip_when_no_matches(self):
        results = check_J06_fuzzy_match_semantic_validation(None, pd.DataFrame())
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_skip_when_no_holdings(self):
        df = _matches([{"match_method": "D_fuzzy"}])
        results = check_J06_fuzzy_match_semantic_validation(df, None)
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_pass_correct_de_matches(self, monkeypatch):
        """D/E matches with consistent identifiers/classifications -> pass."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        matches = _matches([
            {"match_method": "D_fuzzy",
             "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
             "begin_issuer_name": "Acme Corp", "end_issuer_name": "Acme Corp",
             "begin_fair_value": "1000000", "end_fair_value": "1050000"},
        ])
        holdings = _holdings([
            {"cik": "0001287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "bdc_investment_identifier": "Acme Corp First Lien Term Loan",
             "index_classification": "DIRECT_LENDING"},
            {"cik": "0001287750", "report_date": "2024-06-30",
             "issuer_name": "Acme Corp", "fair_value": "1050000",
             "bdc_investment_identifier": "Acme Corp First Lien Term Loan",
             "index_classification": "DIRECT_LENDING"},
        ])
        results = check_J06_fuzzy_match_semantic_validation(matches, holdings)
        cik_results = [r for r in results if r.cik == "0001287750"]
        assert len(cik_results) == 1
        assert cik_results[0].status == "pass"

    def test_warn_name_divergence(self, monkeypatch):
        """D match with very different raw identifiers -> suspect."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        matches = _matches([
            {"match_method": "D_fuzzy",
             "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
             "begin_issuer_name": "Acme Corp", "end_issuer_name": "Acme Corp",
             "begin_fair_value": "1000000", "end_fair_value": "1050000"},
        ])
        # Use maximally divergent raw identifiers to ensure JW < 0.5
        holdings = _holdings([
            {"cik": "0001287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "bdc_investment_identifier": "ZYXWVU QPONML",
             "index_classification": "DIRECT_LENDING"},
            {"cik": "0001287750", "report_date": "2024-06-30",
             "issuer_name": "Acme Corp", "fair_value": "1050000",
             "bdc_investment_identifier": "ABCDEF GHIJKL",
             "index_classification": "DIRECT_LENDING"},
        ])
        results = check_J06_fuzzy_match_semantic_validation(matches, holdings)
        cik_results = [r for r in results if r.cik == "0001287750"]
        assert len(cik_results) == 1
        # With only 1 match total and it's suspect, rate = 100% > 15%
        assert cik_results[0].status == "warn"

    def test_warn_classification_flip(self, monkeypatch):
        """D match with different index_classification -> suspect."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        matches = _matches([
            {"match_method": "D_fuzzy",
             "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
             "begin_issuer_name": "Beta Inc", "end_issuer_name": "Beta Inc",
             "begin_fair_value": "500000", "end_fair_value": "520000"},
        ])
        holdings = _holdings([
            {"cik": "0001287750", "report_date": "2024-03-31",
             "issuer_name": "Beta Inc", "fair_value": "500000",
             "bdc_investment_identifier": "Beta Inc Term Loan",
             "index_classification": "DIRECT_LENDING"},
            {"cik": "0001287750", "report_date": "2024-06-30",
             "issuer_name": "Beta Inc", "fair_value": "520000",
             "bdc_investment_identifier": "Beta Inc Term Loan",
             "index_classification": "EQUITY"},
        ])
        results = check_J06_fuzzy_match_semantic_validation(matches, holdings)
        cik_results = [r for r in results if r.cik == "0001287750"]
        assert len(cik_results) == 1
        assert cik_results[0].status == "warn"

    def test_b2_tiers_excluded(self, monkeypatch):
        """B2 matches should not be evaluated by J06."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        matches = _matches([
            {"match_method": "B2_exact_name",
             "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
             "begin_issuer_name": "Acme Corp", "end_issuer_name": "Acme Corp",
             "begin_fair_value": "1000000", "end_fair_value": "1050000"},
        ])
        holdings = _holdings([
            {"cik": "0001287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "bdc_investment_identifier": "X", "index_classification": "A"},
            {"cik": "0001287750", "report_date": "2024-06-30",
             "issuer_name": "Acme Corp", "fair_value": "1050000",
             "bdc_investment_identifier": "Y", "index_classification": "B"},
        ])
        results = check_J06_fuzzy_match_semantic_validation(matches, holdings)
        # Should skip -- no D/E tier matches
        assert all(r.status == "skip" for r in results)


# ===================================================================
# Jaro-Winkler Helper
# ===================================================================

class TestJaroWinklerPy:
    """Tests for the pure-Python Jaro-Winkler implementation."""

    def test_identical_strings(self):
        assert _jaro_winkler_py("hello", "hello") == 1.0

    def test_empty_strings(self):
        assert _jaro_winkler_py("", "") == 1.0
        assert _jaro_winkler_py("hello", "") == 0.0
        assert _jaro_winkler_py("", "hello") == 0.0

    def test_completely_different(self):
        score = _jaro_winkler_py("abc", "xyz")
        assert score == 0.0

    def test_similar_strings(self):
        score = _jaro_winkler_py("acme corp term loan", "acme corp term loan a")
        assert score > 0.9

    def test_divergent_strings(self):
        score = _jaro_winkler_py("abcdef", "zyxwvu")
        assert score < 0.5


# ===================================================================
# DIAGNOSTIC: diagnose_fuzzy_fallbacks
# ===================================================================

class TestDiagnoseFuzzyFallbacks:
    """Tests for diagnose_fuzzy_fallbacks()."""

    def test_basic_diagnostic(self):
        """D_fuzzy match joined to unified shows position keys + diff."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        matches = pd.DataFrame([{
            "cik": "0001287750",
            "match_method": "D_fuzzy",
            "begin_report_date": "2024-03-31",
            "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp",
            "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000",
            "end_fair_value": "1050000",
            "match_score": "0.92",
        }])
        unified = pd.DataFrame([
            {"cik": "1287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "position_key": "acme corp first lien 7.5"},
            {"cik": "1287750", "report_date": "2024-06-30",
             "issuer_name": "Acme Corp", "fair_value": "1050000",
             "position_key": "acme corp first lien 8.0"},
        ])

        result = diagnose_fuzzy_fallbacks(matches, unified)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["begin_position_key"] == "acme corp first lien 7.5"
        assert row["end_position_key"] == "acme corp first lien 8.0"
        assert "tokens differ" in row["key_diff_summary"]
        assert "7.5" in row["key_diff_summary"]
        assert "8.0" in row["key_diff_summary"]

    def test_empty_matches(self):
        """Empty matches_df returns empty DataFrame."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        result = diagnose_fuzzy_fallbacks(pd.DataFrame(), pd.DataFrame())
        assert result.empty

    def test_no_fuzzy_matches(self):
        """Non-D_fuzzy rows produce empty result."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        matches = pd.DataFrame([{
            "cik": "0001287750",
            "match_method": "B1b_position_key",
            "begin_report_date": "2024-03-31",
            "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp",
            "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000",
            "end_fair_value": "1050000",
        }])
        unified = pd.DataFrame([
            {"cik": "1287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "position_key": "acme corp first lien"},
        ])

        result = diagnose_fuzzy_fallbacks(matches, unified)
        assert result.empty

    def test_missing_position_key_column(self):
        """Unified without position_key returns empty + warning."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        matches = pd.DataFrame([{
            "cik": "0001287750",
            "match_method": "D_fuzzy",
            "begin_report_date": "2024-03-31",
            "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp",
            "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000",
            "end_fair_value": "1050000",
        }])
        unified = pd.DataFrame([
            {"cik": "1287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000"},
        ])

        result = diagnose_fuzzy_fallbacks(matches, unified)
        assert result.empty

    def test_identical_position_keys(self):
        """Same key on both sides produces 'identical keys' summary."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        matches = pd.DataFrame([{
            "cik": "0001287750",
            "match_method": "D_fuzzy",
            "begin_report_date": "2024-03-31",
            "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp",
            "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000",
            "end_fair_value": "1050000",
            "match_score": "0.90",
        }])
        unified = pd.DataFrame([
            {"cik": "1287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "position_key": "acme corp first lien"},
            {"cik": "1287750", "report_date": "2024-06-30",
             "issuer_name": "Acme Corp", "fair_value": "1050000",
             "position_key": "acme corp first lien"},
        ])

        result = diagnose_fuzzy_fallbacks(matches, unified)
        assert len(result) == 1
        assert result.iloc[0]["key_diff_summary"] == "identical keys"

    def test_duplicate_unified_lookup_keeps_one_diagnostic_row(self):
        """Duplicate same issuer/date/FV lookup rows should not expand diagnostics."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        matches = pd.DataFrame([{
            "cik": "0001766037",
            "match_method": "D_fuzzy",
            "begin_report_date": "2025-12-31",
            "end_report_date": "2026-03-31",
            "begin_issuer_name": "AAH Topco, LLC",
            "end_issuer_name": "AAH Topco, LLC",
            "begin_fair_value": "1000000",
            "end_fair_value": "1050000",
            "match_score": "0.88",
        }])
        unified = pd.DataFrame([
            {"cik": "1766037", "report_date": "2025-12-31",
             "issuer_name": "AAH Topco, LLC", "fair_value": "1000000",
             "position_key": "aah topco llc first lien 1"},
            {"cik": "1766037", "report_date": "2026-03-31",
             "issuer_name": "AAH Topco, LLC", "fair_value": "1050000",
             "position_key": "aah topco llc first lien 1"},
            {"cik": "1766037", "report_date": "2026-03-31",
             "issuer_name": "AAH Topco, LLC", "fair_value": "1050000",
             "position_key": "aah topco llc first lien 1 duplicate"},
        ])

        result = diagnose_fuzzy_fallbacks(matches, unified)

        assert len(result) == 1
        assert result.iloc[0]["end_position_key"] == "aah topco llc first lien 1"


# ---------------------------------------------------------------------------
# J07: Hard Gate Rejection Audit
# ---------------------------------------------------------------------------

class TestJ07HardGateRejectionAudit:

    def test_skip_on_empty_matches(self):
        results = check_J07_hard_gate_rejection_audit(pd.DataFrame(), pd.DataFrame())
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_pass_with_cde_matches(self):
        """J07 always passes -- it is an informational audit."""
        matches = pd.DataFrame([{
            "cik": "0001000001", "match_method": "C_normalized_name",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp", "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000", "end_fair_value": "1010000",
            "source": "bdc",
        }])
        holdings = pd.DataFrame([{
            "cik": "0001000001", "report_date": "2024-03-31",
            "issuer_name": "Acme Corp", "source": "bdc",
            "fair_value": "1000000", "index_classification": "DIRECT_LENDING",
            "maturity_date": "2026-06-30",
            "instrument_description": "Senior Term Loan",
        }, {
            "cik": "0001000001", "report_date": "2024-06-30",
            "issuer_name": "Acme Corp", "source": "bdc",
            "fair_value": "1010000", "index_classification": "DIRECT_LENDING",
            "maturity_date": "2026-06-30",
            "instrument_description": "Senior Term Loan",
        }])
        results = check_J07_hard_gate_rejection_audit(matches, holdings)
        assert len(results) == 1
        assert results[0].status == "pass"
        assert "classification_flip=0" in results[0].message

    def test_skip_when_no_cde_tiers(self):
        """J07 skips when all matches are B1/B2 (no C/D/E)."""
        matches = pd.DataFrame([{
            "cik": "0001000001", "match_method": "B1_cusip",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp", "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000", "end_fair_value": "1010000",
            "source": "bdc",
        }])
        holdings = pd.DataFrame([{
            "cik": "0001000001", "report_date": "2024-03-31",
            "issuer_name": "Acme Corp", "source": "bdc",
            "fair_value": "1000000",
        }])
        results = check_J07_hard_gate_rejection_audit(matches, holdings)
        assert len(results) == 1
        assert results[0].status == "pass"  # No C/D/E -> passes with 0 pairs


# ---------------------------------------------------------------------------
# J08: Suspected Refinancing Detection
# ---------------------------------------------------------------------------

class TestJ08SuspectedRefinancing:

    def test_skip_on_empty_matches(self):
        results = check_J08_suspected_refinancing_detection(
            pd.DataFrame(), pd.DataFrame()
        )
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_pass_no_refinancing(self):
        """J08 passes when no maturity+spread shifts detected."""
        matches = pd.DataFrame([{
            "cik": "0001000001", "match_method": "B2_exact_name",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Stable Corp", "end_issuer_name": "Stable Corp",
            "begin_fair_value": "1000000", "end_fair_value": "1010000",
            "source": "bdc",
        }])
        holdings = pd.DataFrame([{
            "cik": "0001000001", "report_date": "2024-03-31",
            "issuer_name": "Stable Corp", "source": "bdc",
            "fair_value": "1000000",
            "maturity_date": "2026-06-30", "basis_spread": "3.5",
            "interest_rate": "8.5",
        }, {
            "cik": "0001000001", "report_date": "2024-06-30",
            "issuer_name": "Stable Corp", "source": "bdc",
            "fair_value": "1010000",
            "maturity_date": "2026-06-30", "basis_spread": "3.5",
            "interest_rate": "8.5",
        }])
        results = check_J08_suspected_refinancing_detection(matches, holdings)
        assert len(results) == 1
        assert results[0].status == "pass"

    def test_warn_on_refinancing(self):
        """J08 warns when maturity shift + spread change exceeds threshold."""
        matches = pd.DataFrame([{
            "cik": "0001000001", "match_method": "B2_exact_name",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Refi Corp", "end_issuer_name": "Refi Corp",
            "begin_fair_value": "1000000", "end_fair_value": "1010000",
            "source": "bdc",
        }])
        holdings = pd.DataFrame([{
            "cik": "0001000001", "report_date": "2024-03-31",
            "issuer_name": "Refi Corp", "source": "bdc",
            "fair_value": "1000000",
            "maturity_date": "2025-06-30", "basis_spread": "3.5",
            "interest_rate": "8.5",
        }, {
            "cik": "0001000001", "report_date": "2024-06-30",
            "issuer_name": "Refi Corp", "source": "bdc",
            "fair_value": "1010000",
            "maturity_date": "2028-06-30", "basis_spread": "2.5",
            "interest_rate": "7.5",
        }])
        results = check_J08_suspected_refinancing_detection(
            matches, holdings, max_refi_rate=0.0
        )
        assert len(results) == 1
        # With only 1 match that is a refi, rate=100% > 0% threshold -> warn
        assert results[0].status == "warn"


# ===================================================================
# Published basis (owner ruling 2026-09-30): fund-level checks exclude
# accounting_record_class == 'underlying_schedule' rows.
# ===================================================================

class TestPublishedBasisFundLevelChecks:
    def _two_rows(self, parent_fv="95000000", jv_fv="95000000", **extra):
        return _holdings([
            {"fair_value": parent_fv, "accounting_record_class": "parent_schedule", **extra},
            {"fair_value": jv_fv, "accounting_record_class": "underlying_schedule", **extra},
        ])

    def test_A04_excludes_underlying_schedule(self):
        ff = _fund_financials([{"investments_at_fair_value": "100000000"}])
        results = check_A04_gav_reconciliation(self._two_rows(), ff)
        assert [r.status for r in results] == ["pass"]
        assert "holdings_fv=95,000,000" in results[0].message

    def test_A04_frame_without_column_keeps_all_rows(self):
        holdings = _holdings([{"fair_value": "95000000"}, {"fair_value": "95000000"}])
        ff = _fund_financials([{"investments_at_fair_value": "100000000"}])
        results = check_A04_gav_reconciliation(holdings, ff)
        assert [r.status for r in results] == ["fail"]

    def test_E01_excludes_underlying_schedule(self):
        from pipeline.oracle_checks import check_E01_holdings_fv_vs_investments
        ff = _fund_financials([{"investments_at_fair_value": "100000000"}])
        results = check_E01_holdings_fv_vs_investments(self._two_rows(), ff)
        assert [(r.check_id, r.status) for r in results] == [("E01", "pass")]

    @staticmethod
    def _pct_rows():
        # 5 parent rows at 20% (100%) + 10 JV rows at 20% (200%): 300% unmasked.
        return _holdings(
            [{"pct_of_net_assets": "20", "accounting_record_class": "parent_schedule"}] * 5
            + [{"pct_of_net_assets": "20", "accounting_record_class": "underlying_schedule"}] * 10
        )

    def test_A07_excludes_underlying_schedule(self):
        results = check_A07_pct_of_net_assets_sum(self._pct_rows())
        assert [r.status for r in results] == ["pass"]
        assert "pct_sum=100.0%" in results[0].message

    def test_A07_frame_without_column_keeps_all_rows(self):
        holdings = self._pct_rows().drop(columns=["accounting_record_class"])
        results = check_A07_pct_of_net_assets_sum(holdings)
        assert [r.status for r in results] == ["fail"]
        assert "pct_sum=300.0%" in results[0].message

    def test_E02_excludes_underlying_schedule(self):
        ff = _fund_financials([{"total_assets": "120000000"}])
        results = check_E02_holdings_fv_vs_total_assets(
            self._two_rows(parent_fv="100000000", jv_fv="100000000"), ff)
        assert [r.status for r in results] == ["pass"]

    def test_E02_frame_without_column_keeps_all_rows(self):
        holdings = _holdings([{"fair_value": "100000000"}, {"fair_value": "100000000"}])
        ff = _fund_financials([{"total_assets": "120000000"}])
        results = check_E02_holdings_fv_vs_total_assets(holdings, ff)
        assert [r.status for r in results] == ["fail"]

    def test_E07_still_counts_underlying_rows(self):
        """E07 compares source leaf counts (which include JV-schedule leaves) to output
        row counts; it is a completeness check, not a fund-level FV total, so it keeps
        every row."""
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf", "source_row_id": str(i)}
            for i in range(2)
        ])
        results = check_E07_position_count_vs_filing(detail, self._two_rows())
        assert [r.status for r in results] == ["pass"]
