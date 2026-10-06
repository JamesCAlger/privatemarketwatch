"""Net investment income ratio from companyfacts: an annualised year-to-date ratio is not a running total.

Ares Capital (CIK 1287750) files InvestmentCompanyInvestmentIncomeLossRatio annualised for each
year-to-date period: 0.1096 for Q1 2025, 0.1042 for the half year, 0.1013 for nine months, 0.1024
for the year. Subtracting the previous period gave -0.54 pct, -0.29 pct and 0.11 pct for Q2 to Q4.
Of the 60 cohort funds that file the ratio, 39 always annualise it and 14 nearly always
(scratch scan of the cached companyfacts, 2026-10-06). Real filed values.
"""
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


def test_ratio_filed_as_a_running_total_is_still_split_by_quarter():
    running = [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 0.025},
        {"start": "2025-01-01", "end": "2025-06-30", "val": 0.051},
        {"start": "2025-01-01", "end": "2025-09-30", "val": 0.078},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 0.102},
    ]
    result = _extract_duration_series(_facts(running), [CONCEPT], "pure", ratio=True)
    assert abs(result["2025-06-30"] - 0.026) < 1e-9
    assert abs(result["2025-09-30"] - 0.027) < 1e-9
    assert abs(result["2025-12-31"] - 0.024) < 1e-9


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
