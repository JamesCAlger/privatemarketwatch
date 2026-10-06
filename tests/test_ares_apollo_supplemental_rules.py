"""Ares (CIK 1287750) and Apollo Debt Solutions (CIK 1837532): rows that are not positions.

Ares tags issuer-level fair values with the investment identifier axis using the issuer names alone;
Apollo's filings carry one industry-and-instrument subtotal and one row repeating another loan's
facts. Real filing values; synthetic frames; no production files touched.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline.agent_promoted import late_resolved_columns
from pipeline.agent_rule import apply_rules, validate_rule

RULES = Path(__file__).resolve().parent.parent / "data" / "overrides" / "agent_investigate_rules"


def _rule(cik, rule_id):
    return json.loads((RULES / cik / (rule_id + ".json")).read_text(encoding="utf-8-sig"))


def _row(cik, identifier, fv, quarter, principal=None, shares=None, maturity=None):
    return {"cik": cik, "report_date": quarter, "issuer_name": identifier, "bdc_investment_identifier": identifier,
            "bdc_dimensions_raw": "investmentidentifieraxis=" + identifier, "fair_value": fv, "principal_amount": principal,
            "shares_held": shares, "pct_of_net_assets": None, "maturity_date": maturity}


def _kept(rule, rows):
    out, audits = apply_rules(pd.DataFrame(rows), [rule])
    assert all(a.get("status") == "ok" for a in audits), audits
    return set(out["bdc_investment_identifier"])


@pytest.mark.parametrize("cik,rule_id", [
    ("1287750", "exclude_issuer_only_supplemental_rows"),
    ("1837532", "exclude_industry_instrument_subtotal_rows"),
])
def test_structural_rules_are_valid_and_cover_every_quarter(cik, rule_id):
    rule = _rule(cik, rule_id)
    assert validate_rule(rule) == []
    assert late_resolved_columns(rule) == []
    assert rule["scope"]["quarters"] == ["all"]
    assert "report_date" not in rule["predicate_sql"] and "row_id" not in rule["predicate_sql"]


@pytest.mark.parametrize("quarter", ["2022-09-30", "2024-09-30", "2025-12-31"])
def test_ares_issuer_only_rows_are_excluded_and_schedule_rows_kept(quarter):
    rule = _rule("1287750", "exclude_issuer_only_supplemental_rows")
    kept = _kept(rule, [
        _row("1287750", "Visual Edge Technology, Inc.", 78_700_000.0, quarter),
        _row("1287750", "Shoes For crews Global, LLC and Shoes for crews Holdings, LLC", 21_500_000.0, quarter),
        _row("1287750", "Olympia Acquisition, Inc., Olympia TopCo, L.P. and Asclepius Hodlings LLC", 48_600_000.0, quarter),
        _row("1287750", "PCG-TAC-CV, LP (fka PCG-Ares Sidecar Investment II, L.P.) 1", 6_700_000.0, quarter),
        _row("1287750", "Visual Edge Technology, Inc., VEIT, LLC, and VEIT Topco, LLC, First lien senior secured loan 2",
             34_400_000.0, quarter, principal=34_400_000.0),
        _row("1287750", "Visual Edge Technology, Inc., VEIT, LLC, and VEIT Topco, LLC, Common units", 14_400_000.0, quarter,
             shares=4_000_000.0),
    ])
    assert kept == {"Visual Edge Technology, Inc., VEIT, LLC, and VEIT Topco, LLC, First lien senior secured loan 2",
                    "Visual Edge Technology, Inc., VEIT, LLC, and VEIT Topco, LLC, Common units"}


def test_ares_rows_naming_an_instrument_or_carrying_a_quantity_are_kept():
    rule = _rule("1287750", "exclude_issuer_only_supplemental_rows")
    kept = _kept(rule, [
        # no instrument in the tag, but a principal: a real loan (2025-03-31)
        _row("1287750", "Expereo USA, Inc. and Ristretto Bidco B.V.", 60_200_000.0, "2025-03-31", principal=60_800_000.0),
        # instrument named, no quantity tagged
        _row("1287750", "Ivy Hill Asset Management, L.P., Member interest", 1_899_000_000.0, "2026-03-31"),
        _row("1287750", "Partnership Capital Growth Investors III, L.P., Limited partnership interest", 3_600_000.0, "2025-03-31"),
        _row("1287750", "OTG Concessions Management, LLC and Octa Parent Holdings, LLC, Participation rights", 0.0, "2025-03-31"),
        _row("1287750", "Doxim Inc. First lien senior secured loan", 83_900_000.0, "2024-06-30"),
    ])
    assert len(kept) == 5


def test_apollo_industry_and_instrument_heading_is_excluded():
    rule = _rule("1837532", "exclude_industry_instrument_subtotal_rows")
    loan = ("Insurance Alera Group Alera Group, Inc. Investment Type First Lien Secured Debt - Revolver Interest Rate S+525, "
            "0.75% Floor Maturity Date 9/30/2028")
    undrawn = ("Software Anaplan Anaplan, Inc. Investment Type First Lien Secured Debt – Revolver Interest Rate S+450, 0.75% "
               "Floor Maturity Date 6/21/2028")
    later_format = "MachineryJPW JPW Industries Holding Corporation First Lien Secured Debt - Term Loan S+588, 2.00% Floor 11/22/2028"
    kept = _kept(rule, [
        _row("1837532", "Insurance First Lien Secured Debt - Revolver", 50_488_000.0, "2024-03-31"),
        _row("1837532", loan, 1_200_000.0, "2024-03-31", principal=1_250_000.0, maturity="2028-09-30"),
        _row("1837532", undrawn, -70_000.0, "2025-06-30", maturity="2028-06-21"),
        _row("1837532", later_format, 114_090_000.0, "2024-06-30", principal=116_420_000.0, maturity="2028-11-22"),
    ])
    assert kept == {loan, undrawn, later_format}


def test_apollo_repeated_genesys_facts_are_excluded_in_their_quarter_only():
    rule = _rule("1837532", "exclude_2023q3_genesys_repeated_facts")
    assert validate_rule(rule) == [] and rule["scope"]["quarters"] == ["2023-09-30"]
    stale = ("IT Services Genesys Cloud Greeneden U.S. Holdings II, LLC Investment Type First Lien Secured Debt Interest Rate "
             "L+400, 0.75% Floor Maturity Date 12/1/2027")
    live = ("IT Services Genesys Cloud Greeneden U.S. Holdings II, LLC Investment Type First Lien Secured Debt Interest Rate "
            "L+411, 0.75% Floor Maturity Date 12/1/2027")
    esdec = ("Independent Power & Renewable Electricity Producers Esdec Esdec Solar Group B.V. Investment Type First Lien "
             "Secured Debt Interest Rate E+600, 0.50% Floor Maturity Date 8/30/2028")
    kept = _kept(rule, [
        _row("1837532", stale, 50_510_000.0, "2023-09-30"),
        _row("1837532", live, 11_235_000.0, "2023-09-30", principal=11_213_000.0),
        _row("1837532", esdec, 50_510_000.0, "2023-09-30", principal=65_000_000.0),
    ])
    assert kept == {live, esdec}
    # its own values a year earlier are a real position
    earlier = _kept(rule, [_row("1837532", stale, 38_810_000.0, "2022-12-31", principal=40_350_000.0)])
    assert earlier == {stale}


@pytest.mark.parametrize("identifier,family", [
    ("ARES 2007-3R, Subordinated notes", "debt"),                    # 0.1M, every quarter to 2024-03-31
    ("Nordic Ferry Infrastructure AS, Senior subordinated loan 1", "debt"),
    ("CREST Exeter Street Solar 2004-1, Preferred shares", "equity"),
])
def test_ares_positions_whose_issuer_has_no_legal_suffix_are_leaves(identifier, family):
    """Ares identifies every position as '<issuer>, <instrument>'; it files no category rows under
    the identifier axis. These three fell through to '<family>_category_rollup' and were dropped
    (the fund's 0.1M to 0.2M shortfall in 13 quarters, fund sandbox 2026-10-06)."""
    from pipeline.bdc_xbrl_wrapper import classify_identifier
    assert classify_identifier("0001287750", identifier)["wrapper_disposition"] == family + "_position_leaf"


@pytest.mark.parametrize("identifier", ["Total investments", "Sub-total", "Software and Services"])
def test_ares_totals_and_headings_are_not_leaves(identifier):
    from pipeline.bdc_xbrl_wrapper import classify_identifier
    assert not classify_identifier("0001287750", identifier)["wrapper_disposition"].endswith("_position_leaf")


@pytest.mark.parametrize("rule_id,quarter,total", [
    ("recover_2025q1_values_tagged_on_issuer_axis", "2025-03-31", 94_300_000.0),
    ("recover_2025q2_values_tagged_on_issuer_axis", "2025-06-30", 33_200_000.0),
])
def test_ares_positions_valued_on_the_issuer_axis_are_restored_once(rule_id, quarter, total):
    """Two Ares filings put four positions' cost and fair value on the context after the position's
    own (issuer-name axis). The rows are added back with the filed values; the totals are the
    fund's shortfall in those quarters to the dollar. Adding twice must not duplicate them."""
    rule = _rule("1287750", rule_id)
    assert validate_rule(rule) == [] and rule["scope"]["quarters"] == [quarter]
    assert sum(p["fair_value"] for p in rule["positions"]) == total
    for position in rule["positions"]:
        assert position["index_classification"] and position["asset_category"] and position["accession_number"]
        assert position["src_context_id"].startswith("c-") and position["fair_value_source"] == "xbrl_field"
    frame = pd.DataFrame([dict(_row("1287750", "Other Borrower, Inc., First lien senior secured loan", 1_000_000.0, quarter,
                                    principal=1_000_000.0),
                               accession_number="x", index_classification="DIRECT_LENDING", asset_category="LOAN",
                               src_context_id="c-1", fair_value_source="xbrl_field", cost=1_000_000.0)])
    once, audits = apply_rules(frame, [rule])
    assert all(a.get("status") == "ok" for a in audits), audits
    assert len(once) == 5 and once["fair_value"].sum() == pytest.approx(total + 1_000_000.0)
    twice, _ = apply_rules(once, [rule])
    assert len(twice) == 5
