"""NAV per share from per-class filing facts, when the entity-level fact is wrong or absent.

HPS (0001838126) tags the "$1,000 of indebtedness" in its senior-securities footnote as
us-gaap:NetAssetValuePerShare with no share class, and reports the real figure per class.
"""
import pandas as pd
import pytest

from pipeline.bdc_fund_highlights import _dedup_highlights
from pipeline.fund_financials import _prepare_bdc, class_nav_consensus


def _balance(nav, net_assets=12434974000.0, shares=501538142.0):
    return pd.DataFrame([{
        "cik": "1838126", "report_date": "2026-03-31", "total_assets": 27.0e9,
        "total_liabilities": 14.5e9, "net_assets": net_assets, "nav_per_share": nav,
        "shares_outstanding": shares, "borrowings": 13.0e9}])


def _classes(values, period_end="2026-03-31", quarter="2026q1", period_type="instant"):
    return pd.DataFrame([
        dict(cik="0001838126", report_quarter=quarter, period_end=period_end,
             period_type=period_type, share_class=name, nav_per_share=value)
        for name, value in values.items()])


HPS = frozenset({"0001838126"})
AGREED = {"ClassI": 24.79, "ClassD": 24.79, "ClassF": 24.79, "ClassS": 24.79}


def _nav(result):
    return float(result.iloc[0]["nav_per_share"])


def test_consensus_is_the_shared_quarter_end_class_value():
    out = class_nav_consensus(_classes(AGREED), HPS)
    assert out.to_dict("records") == [dict(cik="0001838126", report_quarter="2026q1", class_nav=24.79)]


def test_no_consensus_when_classes_disagree():
    assert class_nav_consensus(_classes(dict(AGREED, ClassS=24.61)), HPS).empty


def test_consensus_ignores_entity_level_duration_and_mid_quarter_rows():
    noise = pd.concat([
        _classes({"": 1000.0}),
        _classes({"ClassI": -0.43}, period_type="duration"),
        _classes({"ClassI": 25.10}, period_end="2026-03-10"),
    ])
    assert class_nav_consensus(noise, HPS).empty
    out = class_nav_consensus(pd.concat([noise, _classes(AGREED)]), HPS)
    assert out["class_nav"].tolist() == [24.79]


def test_class_value_replaces_an_entity_value_that_breaks_the_identity():
    result = _prepare_bdc(_balance(1000.0), pd.DataFrame(), class_nav_df=class_nav_consensus(_classes(AGREED), HPS))
    assert _nav(result) == pytest.approx(24.79)


def test_class_value_fills_a_missing_entity_value():
    result = _prepare_bdc(_balance(None), pd.DataFrame(), class_nav_df=class_nav_consensus(_classes(AGREED), HPS))
    assert _nav(result) == pytest.approx(24.79)


def test_entity_value_that_satisfies_the_identity_is_kept():
    wrong_classes = {name: 30.0 for name in AGREED}
    result = _prepare_bdc(_balance(24.79), pd.DataFrame(), class_nav_df=class_nav_consensus(_classes(wrong_classes), HPS))
    assert _nav(result) == pytest.approx(24.79)


def test_class_value_that_also_breaks_the_identity_is_not_used():
    wrong_classes = {name: 50.0 for name in AGREED}
    result = _prepare_bdc(_balance(1000.0), pd.DataFrame(), class_nav_df=class_nav_consensus(_classes(wrong_classes), HPS))
    assert _nav(result) == pytest.approx(1000.0)


def test_without_class_facts_the_entity_value_is_unchanged():
    assert _nav(_prepare_bdc(_balance(1000.0), pd.DataFrame())) == pytest.approx(1000.0)


def _highlight(period_end, form, nav, shares, accession):
    return dict(cik="0001838126", entity_name="HPS", accession_number=accession, form_type=form,
                filing_date="2026-05-11", period_end=period_end, period_start=None, period_type="instant",
                duration_months=0, share_class="ClassI", report_quarter="2026q1",
                nav_per_share=nav, shares_outstanding=shares)


def test_dedup_keeps_the_quarter_end_instant_over_a_cover_page_date():
    frame = pd.DataFrame([
        _highlight("2026-03-10", "10-K", None, 207774660.0, "A"),   # cover-page share count
        _highlight("2026-03-31", "10-Q", 24.79, None, "B"),         # quarter-end class NAV
    ])
    out = _dedup_highlights(frame, quarter_end_ciks=HPS)
    assert out[["period_end", "nav_per_share"]].values.tolist() == [["2026-03-31", 24.79]]


def test_dedup_still_prefers_the_annual_report_between_two_quarter_end_instants():
    frame = pd.DataFrame([
        _highlight("2026-03-31", "10-Q", 24.79, None, "B"),
        _highlight("2026-03-31", "10-K", 24.80, None, "A"),
    ])
    assert _dedup_highlights(frame, quarter_end_ciks=HPS)["accession_number"].tolist() == ["A"]


def test_a_fund_that_has_not_opted_in_gets_no_consensus():
    assert class_nav_consensus(_classes(AGREED)).empty
    assert class_nav_consensus(_classes(AGREED), frozenset({"0001287750"})).empty


def test_dedup_is_unchanged_for_a_fund_that_has_not_opted_in():
    frame = pd.DataFrame([
        _highlight("2026-03-10", "10-K", None, 207774660.0, "A"),
        _highlight("2026-03-31", "10-Q", 24.79, None, "B"),
    ])
    assert _dedup_highlights(frame)["accession_number"].tolist() == ["A"]


def test_the_hps_wrapper_opts_in_and_no_other_fund_does():
    from pathlib import Path

    from pipeline import fund_highlights_wrapper as fhw
    store = Path(__file__).resolve().parents[1] / "data" / "overrides" / "fund_highlights_wrappers"
    specs = [fhw._load_wrapper_from_path(p) for p in sorted(store.glob("*.json"))]
    opted = {s.cik for s in specs if s and s.source_preferences.get("nav_per_share") == fhw.CLASS_NAV_PREFERENCE}
    assert opted == {"0001838126"}
