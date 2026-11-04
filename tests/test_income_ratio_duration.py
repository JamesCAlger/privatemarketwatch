"""Net investment income ratio from companyfacts: an annualised year-to-date ratio is not a running total.

Ares Capital (CIK 1287750) files InvestmentCompanyInvestmentIncomeLossRatio annualised for each
year-to-date period: 0.1096 for Q1 2025, 0.1042 for the half year, 0.1013 for nine months, 0.1024
for the year. Subtracting the previous period gave -0.54 pct, -0.29 pct and 0.11 pct for Q2 to Q4.
Of the 60 cohort funds that file the ratio, 39 always annualise it and 14 nearly always
(scratch scan of the cached companyfacts, 2026-10-06). Real filed values.
"""
import pytest

from pipeline.extract_companyfacts import _extract_duration_series

CONCEPT = "InvestmentCompanyInvestmentIncomeLossRatio"


def _facts(entries):
    return {"facts": {"us-gaap": {CONCEPT: {"units": {"pure": entries}}}}}


ARES_2025 = [
    {"start": "2025-01-01", "end": "2025-03-31", "val": 0.1096},
    {"start": "2025-01-01", "end": "2025-06-30", "val": 0.1042},
    {"start": "2025-01-01", "end": "2025-09-30", "val": 0.1013},
    {"start": "2025-01-01", "end": "2025-12-31", "val": 0.1024},
]


def test_annualised_year_to_date_ratio_is_kept_as_filed():
    result = _extract_duration_series(_facts(ARES_2025), [CONCEPT], "pure", ratio=True)
    assert result == {"2025-03-31": 0.1096, "2025-06-30": 0.1042, "2025-09-30": 0.1013, "2025-12-31": 0.1024}


# Owner queue f16-income-ratio-printed-not-annualised. CIK 1702510 2025, real filed values; its 10-Qs say
# "(4) These ratios to average net assets attributable to Common Stockholders have not been annualized".
# The split published 2.42 / 2.42 / 2.31 for Q2 to Q4 (one quarter, not annualised) beside funds that
# publish an annualised ratio; F16 compares it with an annualised distribution rate.
RUNNING_2025 = [
    {"start": "2025-01-01", "end": "2025-03-31", "val": 0.0233},
    {"start": "2025-01-01", "end": "2025-06-30", "val": 0.0475},
    {"start": "2025-01-01", "end": "2025-09-30", "val": 0.0717},
    {"start": "2025-01-01", "end": "2025-12-31", "val": 0.0948},
]


def test_ratio_filed_as_a_running_total_is_annualised_not_split():
    result = _extract_duration_series(_facts(RUNNING_2025), [CONCEPT], "pure", ratio=True)
    assert result["2025-03-31"] == pytest.approx(0.0233 * 4)
    assert result["2025-06-30"] == pytest.approx(0.0475 * 2)
    assert result["2025-09-30"] == pytest.approx(0.0717 * 4 / 3)


def test_the_years_ratio_from_a_10k_is_kept_as_filed_on_either_basis():
    running = _extract_duration_series(_facts(RUNNING_2025), [CONCEPT], "pure", ratio=True)
    annualised = _extract_duration_series(_facts(ARES_2025), [CONCEPT], "pure", ratio=True)
    assert running["2025-12-31"] == 0.0948
    assert annualised["2025-12-31"] == 0.1024
    # a 10-K-only filer: the year's ratio is not spread over four quarters
    year_only = _extract_duration_series(_facts([ARES_2025[-1]]), [CONCEPT], "pure", ratio=True)
    assert year_only == {"2025-12-31": 0.1024}


def test_a_three_month_ratio_inside_a_running_total_year_is_annualised():
    # CIK 2012139 2026: "Income and expenses have not been annualized in calculating these ratios"; the
    # 10-Q for 2026-06-30 files the quarter (0.023) beside the six months (0.046).
    filed = [
        {"start": "2026-01-01", "end": "2026-03-31", "val": 0.022},
        {"start": "2026-01-01", "end": "2026-06-30", "val": 0.046},
        {"start": "2026-04-01", "end": "2026-06-30", "val": 0.023},
    ] + RUNNING_2025
    result = _extract_duration_series(_facts(filed), [CONCEPT], "pure", ratio=True)
    assert result["2026-03-31"] == pytest.approx(0.088)
    assert result["2026-06-30"] == pytest.approx(0.092)


def test_one_sharp_rise_in_an_annualised_ratio_is_not_read_as_a_running_total():
    # TCW Direct Lending VII (CIK 1603480) 2022, real filed values: 5.42 for three months, then 8.55 for six
    # months (1.58x, past the 1.5x cut), 7.63 for nine and 7.67 for the year; both 10-Qs print annualised
    # ratios. The old split published 3.13 for 2022-06-30, a figure the filing does not print.
    tcw = [
        {"start": "2022-01-01", "end": "2022-03-31", "val": 0.0542},
        {"start": "2022-01-01", "end": "2022-06-30", "val": 0.0855},
        {"start": "2022-01-01", "end": "2022-09-30", "val": 0.0763},
        {"start": "2022-01-01", "end": "2022-12-31", "val": 0.0767},
    ]
    result = _extract_duration_series(_facts(tcw + ARES_2025), [CONCEPT], "pure", ratio=True)
    assert result["2022-06-30"] == 0.0855
    assert result["2022-03-31"] == 0.0542
    assert result["2025-06-30"] == 0.1042


def test_a_fund_with_a_single_running_vote_is_kept_as_filed():
    # one six-month figure 1.6x the quarter and nothing else to vote: too little to call a basis
    lone = [
        {"start": "2024-01-01", "end": "2024-03-31", "val": 0.050},
        {"start": "2024-01-01", "end": "2024-06-30", "val": 0.080},
    ]
    result = _extract_duration_series(_facts(lone), [CONCEPT], "pure", ratio=True)
    assert result == {"2024-03-31": 0.050, "2024-06-30": 0.080}


def test_amounts_are_split_by_quarter_whatever_their_growth():
    # a per-share amount that happens to be flat year to date is still a running total
    flat = [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 0.48},
        {"start": "2025-01-01", "end": "2025-06-30", "val": 0.50},
    ]
    result = _extract_duration_series({"facts": {"us-gaap": {"Dist": {"units": {"USD/shares": flat}}}}}, ["Dist"], "USD/shares")
    assert abs(result["2025-06-30"] - 0.02) < 1e-9


def test_the_income_ratio_field_is_read_as_a_ratio():
    from pipeline.extract_companyfacts import _INCOME_CONCEPTS
    assert _INCOME_CONCEPTS["income_yield_pct"].get("ratio") is True
    assert not _INCOME_CONCEPTS["income_per_share"].get("ratio")


# Owner ruling 2026-11-04: income_yield_pct is the annualised year-to-date ratio for every fund. A fund
# whose annualised ratio climbs in its first year can trip the running-total vote; its highlights wrapper
# keeps the figures as filed (income_ratio_as_filed). West Bay BDC (CIK 2020354) 2025, real filed values,
# footnote '(4) Ratios are annualized, except for, as applicable, organization costs'.
WEST_BAY_2025 = [
    {"start": "2025-01-01", "end": "2025-03-31", "val": -0.0088},
    {"start": "2025-01-01", "end": "2025-06-30", "val": 0.0229},
    {"start": "2025-01-01", "end": "2025-09-30", "val": 0.0444},
    {"start": "2025-01-01", "end": "2025-12-31", "val": 0.0624},
]


def test_the_vote_misreads_a_first_year_climb_without_the_wrapper():
    result = _extract_duration_series(_facts(WEST_BAY_2025), [CONCEPT], "pure", ratio=True)
    assert result["2025-06-30"] == pytest.approx(0.0458)


def test_the_as_filed_override_keeps_an_annualised_climb_as_filed():
    result = _extract_duration_series(_facts(WEST_BAY_2025), [CONCEPT], "pure", ratio=True,
                                      ratio_as_filed_from="0000-00-00")
    assert result == {"2025-03-31": -0.0088, "2025-06-30": 0.0229, "2025-09-30": 0.0444, "2025-12-31": 0.0624}


def test_the_override_leaves_periods_before_its_start_to_the_vote():
    # Capital Southwest (CIK 17313): printed 'Not annualized' to 2022-12-31, annualised from fiscal 2023
    running_2024 = [dict(e, start="2024-01-01", end=e["end"].replace("2025", "2024")) for e in RUNNING_2025]
    result = _extract_duration_series(_facts(running_2024 + RUNNING_2025), [CONCEPT], "pure", ratio=True,
                                      ratio_as_filed_from="2025-01-01")
    assert result["2024-06-30"] == pytest.approx(0.0475 * 2)
    assert result["2025-06-30"] == 0.0475


def test_the_override_needs_evidence_and_is_absent_by_default(tmp_path):
    import json

    from pipeline.fund_highlights_wrapper import _load_wrapper_from_path
    base = {"schema_version": "fund-highlights-wrapper.v1", "cik": "0002020354", "entity_name": "West Bay", "version": 1}
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps(base))
    assert _load_wrapper_from_path(plain).income_ratio_as_filed_from is None
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps({**base, "income_ratio_as_filed": {"from_period_start": "2025-01-01"}}))
    assert _load_wrapper_from_path(bare).income_ratio_as_filed_from is None
    full = tmp_path / "full.json"
    full.write_text(json.dumps({**base, "income_ratio_as_filed": {"evidence": "(4) Ratios are annualized, except for"}}))
    assert _load_wrapper_from_path(full).income_ratio_as_filed_from == "0000-00-00"


def test_the_shipped_overrides_parse_and_validate_against_the_schema():
    import json
    from pathlib import Path

    import jsonschema

    from pipeline.config import FUND_HIGHLIGHTS_WRAPPER_DIR
    from pipeline.fund_highlights_wrapper import _load_wrapper_from_path
    schema_path = Path(__file__).resolve().parents[1] / "schemas/fund_highlights_wrapper/wrapper_v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    expected = {"0000017313": "2022-04-01", "0001930679": "0000-00-00", "0002020354": "0000-00-00"}
    for cik, start in expected.items():
        path = FUND_HIGHLIGHTS_WRAPPER_DIR / f"{cik}.json"
        jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), schema)
        assert _load_wrapper_from_path(path).income_ratio_as_filed_from == start
