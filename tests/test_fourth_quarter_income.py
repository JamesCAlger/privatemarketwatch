"""A year-end quarter is the annual figure less the three filed quarters, not the annual figure divided by four."""
import duckdb
import pandas as pd
import pytest

from pipeline.fund_financials import _prepare_bdc, quarter_income_sql


def _income(cik, day, months, income, expenses=None, quarter=None):
    year, month = day[:4], int(day[5:7])
    return dict(cik=cik, report_quarter=quarter or "%sq%d" % (year, (month - 1) // 3 + 1), report_date=day,
                duration_months=str(months), total_investment_income=str(income),
                net_investment_income=None, management_fee=None, incentive_fee=None, interest_expense=None,
                total_expenses=None if expenses is None else str(expenses))


def _quarters(rows):
    con = duckdb.connect()
    frame = pd.DataFrame(rows)
    con.register("income", frame)
    out = con.execute("SELECT cik, report_quarter, total_investment_income, total_expenses FROM ("
                      + quarter_income_sql("income", set(frame.columns)) + ") ORDER BY 1, 2").fetchall()
    return {(r[0], r[1]): (r[2], r[3]) for r in out}


# HPS 2023: quarters of 178.8, 215.8 and 233.9; the 10-K's 893.2 is stored as 223.3
HPS_2023 = [_income("1838126", "2023-03-31", 3, 178.8, 80.0), _income("1838126", "2023-06-30", 3, 215.8, 90.0),
            _income("1838126", "2023-09-30", 3, 233.9, 100.0), _income("1838126", "2023-12-31", 12, 223.3, 104.2)]


def test_the_year_end_quarter_is_the_annual_figure_less_three_filed_quarters():
    out = _quarters(HPS_2023)
    assert out[("0001838126", "2023q4")][0] == pytest.approx(4 * 223.3 - 178.8 - 215.8 - 233.9)   # 264.7
    assert out[("0001838126", "2023q4")][1] == pytest.approx(4 * 104.2 - 270.0)
    assert out[("0001838126", "2023q3")] == (233.9, 100.0)          # filed quarters are untouched


def test_a_year_without_three_filed_quarters_keeps_the_stored_figure():
    out = _quarters(HPS_2023[1:])                                    # first quarter missing
    assert out[("0001838126", "2023q4")][0] == 223.3
    # quarters of the year before do not count
    out = _quarters(HPS_2023 + [_income("1838126", "2024-12-31", 12, 356.5)])
    assert out[("0001838126", "2024q4")][0] == 356.5


# Blue Owl Technology Income began on 2022-05-02: two 10-Qs (10,176 and 35,696) and a 10-K of 96,557, stored as 24,139.25
OWLTECH_2022 = [_income("1869453", "2022-06-30", 3, 10176.0, 4485.0), _income("1869453", "2022-09-30", 3, 35696.0, 16659.0),
                _income("1869453", "2022-12-31", 12, 24139.25, 11401.0)]


def _quarters_declared(rows, declared):
    con = duckdb.connect()
    frame = pd.DataFrame(rows)
    con.register("income", frame)
    out = con.execute("SELECT cik, report_quarter, total_investment_income, total_expenses FROM ("
                      + quarter_income_sql("income", set(frame.columns), declared) + ") ORDER BY 1, 2").fetchall()
    return {(r[0], r[1]): (r[2], r[3]) for r in out}


def test_a_declared_first_year_is_the_annual_figure_less_the_quarters_filed():
    out = _quarters_declared(OWLTECH_2022, {("0001869453", "2022-12-31")})
    assert out[("0001869453", "2022q4")][0] == pytest.approx(96557.0 - 10176.0 - 35696.0)      # 50,685
    assert out[("0001869453", "2022q4")][1] == pytest.approx(4 * 11401.0 - 4485.0 - 16659.0)
    assert out[("0001869453", "2022q3")] == (35696.0, 16659.0)      # filed quarters are untouched
    # a figure missing in one of the filed quarters keeps its average
    rows = [dict(r) for r in OWLTECH_2022]
    rows[0]["total_expenses"] = None
    assert _quarters_declared(rows, {("0001869453", "2022-12-31")})[("0001869453", "2022q4")] == (pytest.approx(50685.0), 11401.0)


def test_a_year_with_two_quarters_keeps_the_average_unless_its_fund_and_year_are_declared():
    # not declared at all, as for every other fund
    assert _quarters_declared(OWLTECH_2022, ())[("0001869453", "2022q4")] == (24139.25, 11401.0)
    assert _quarters(OWLTECH_2022)[("0001869453", "2022q4")] == (24139.25, 11401.0)
    # another fund's declaration, and this fund's declaration of another year, do not reach it
    assert _quarters_declared(OWLTECH_2022, {("0001838126", "2022-12-31")})[("0001869453", "2022q4")][0] == 24139.25
    assert _quarters_declared(OWLTECH_2022, {("0001869453", "2023-12-31")})[("0001869453", "2022q4")][0] == 24139.25
    # a declared fund's later year with a quarter missing is not a first year: still the average
    later = OWLTECH_2022 + [_income("1869453", "2023-06-30", 3, 65503.0), _income("1869453", "2023-09-30", 3, 78994.0),
                            _income("1869453", "2023-12-31", 12, 74990.75)]
    assert _quarters_declared(later, {("0001869453", "2022-12-31")})[("0001869453", "2023q4")][0] == 74990.75
    # and a year with three filed quarters is computed as before, declared or not
    assert _quarters_declared(HPS_2023, {("0001838126", "2023-12-31")})[("0001838126", "2023q4")][0] == pytest.approx(264.7)


# New Mountain Guardian IV began on 2022-05-09: 10-Qs of 709 (two months) and 2,004, and a 10-K of 5,877 for eight
# months, stored as 5,877 x 3 / 8 = 2,203.875
GUARDIAN4_2022 = [_income("1925531", "2022-06-30", 2, 709.0, 1096.0), _income("1925531", "2022-09-30", 3, 2004.0, 1414.0),
                  _income("1925531", "2022-12-31", 8, 2203.875, 1781.625)]


def test_a_declared_first_year_shorter_than_twelve_months_is_the_period_figure_less_the_quarters_filed():
    out = _quarters_declared(GUARDIAN4_2022, {("0001925531", "2022-12-31")})
    assert out[("0001925531", "2022q4")][0] == pytest.approx(5877.0 - 709.0 - 2004.0)          # 3,164
    assert out[("0001925531", "2022q4")][1] == pytest.approx(1781.625 * 8 / 3 - 1096.0 - 1414.0)
    assert out[("0001925531", "2022q3")] == (2004.0, 1414.0)
    # a full-year declared first year is unchanged (x 4)
    assert _quarters_declared(OWLTECH_2022, {("0001869453", "2022-12-31")})[("0001869453", "2022q4")][0] == pytest.approx(50685.0)


def test_a_short_annual_period_keeps_the_stored_figure_unless_its_fund_and_year_are_declared():
    assert _quarters(GUARDIAN4_2022)[("0001925531", "2022q4")] == (2203.875, 1781.625)
    assert _quarters_declared(GUARDIAN4_2022, {("0001869453", "2022-12-31")})[("0001925531", "2022q4")][0] == 2203.875
    assert _quarters_declared(GUARDIAN4_2022, {("0001925531", "2023-12-31")})[("0001925531", "2022q4")][0] == 2203.875


def test_a_figure_missing_in_one_quarter_keeps_its_average_while_the_others_are_computed():
    rows = [dict(r) for r in HPS_2023]
    rows[1]["total_expenses"] = None
    out = _quarters(rows)
    assert out[("0001838126", "2023q4")] == (pytest.approx(264.7), 104.2)


def test_a_fund_listed_under_two_spellings_of_its_cik_is_counted_once():
    # the income table holds some funds as both '1287750' and '0001287750'
    doubled = HPS_2023 + [dict(r, cik="0001838126") for r in HPS_2023]
    values = {v for k, v in _quarters(doubled).items() if k[1] == "2023q4"}
    assert len(values) == 1 and next(iter(values))[0] == pytest.approx(264.7)


def test_an_income_table_without_period_columns_is_read_as_before():
    frame = pd.DataFrame([{k: v for k, v in r.items() if k not in ("report_date", "duration_months")} for r in HPS_2023])
    con = duckdb.connect()
    con.register("income", frame)
    out = con.execute("SELECT total_investment_income FROM (" + quarter_income_sql("income", set(frame.columns))
                      + ") WHERE report_quarter = '2023q4'").fetchone()
    assert out[0] == 223.3


def test_fund_financials_publish_the_true_fourth_quarter():
    balance = pd.DataFrame([dict(cik="1838126", report_date=day, total_assets=1e10, total_liabilities=4e9, net_assets=6e9,
                                 nav_per_share=25.0, shares_outstanding=2.4e8, borrowings=3e9)
                            for day in ("2023-09-30", "2023-12-31")])
    result = _prepare_bdc(balance, pd.DataFrame(HPS_2023)).set_index("report_quarter")
    assert float(result.loc["2023q4", "total_investment_income"]) == pytest.approx(264.7)
    assert float(result.loc["2023q3", "total_investment_income"]) == pytest.approx(233.9)


def _facts(entries):
    return {"facts": {"us-gaap": {"NetExpenses": {"units": {"USD": entries}}}}}


def test_companyfacts_year_figure_is_split_by_the_filed_quarters_when_no_nine_month_figure_exists():
    # HPS 2024: each 10-Q files its quarter alone and the 10-K files the year, so there is no nine-month figure to
    # subtract. Net expenses were published as 657.2 / 4 = 164.3 for the fourth quarter.
    from pipeline.extract_companyfacts import _extract_duration_series
    quarters = [{"start": "2024-01-01", "end": "2024-03-31", "val": 140.0}, {"start": "2024-04-01", "end": "2024-06-30", "val": 150.0},
                {"start": "2024-07-01", "end": "2024-09-30", "val": 178.0}]
    year = {"start": "2024-01-01", "end": "2024-12-31", "val": 657.2}
    out = _extract_duration_series(_facts(quarters + [year]), ["NetExpenses"], "USD")
    assert out["2024-12-31"] == pytest.approx(657.2 - 140.0 - 150.0 - 178.0) and out["2024-09-30"] == 178.0
    # a quarter missing: still the average, as before
    assert _extract_duration_series(_facts(quarters[1:] + [year]), ["NetExpenses"], "USD")["2024-12-31"] == pytest.approx(657.2 / 4)
    # an annual-only filer, and an annualised ratio, are spread evenly as before
    assert _extract_duration_series(_facts([year]), ["NetExpenses"], "USD")["2024-12-31"] == pytest.approx(657.2 / 4)
    ratio = _extract_duration_series(_facts(quarters + [year]), ["NetExpenses"], "USD", ratio=True)
    assert ratio["2024-12-31"] == pytest.approx(657.2 / 4)


def test_a_quarter_only_field_gets_no_value_from_a_year_figure_that_cannot_be_split():
    # HPS net expenses for 2024 are filed in the 10-K only (657.357M); the 10-Qs of 2024 do not file the figure.
    # 164.3M, a quarter of the year, was compared with the true fourth quarter's income and gross expenses.
    from pipeline.extract_companyfacts import _extract_duration_series
    earlier = [{"start": "2023-07-01", "end": "2023-09-30", "val": 110.0}]
    year = {"start": "2024-01-01", "end": "2024-12-31", "val": 657.357}
    kept = _extract_duration_series(_facts(earlier + [year]), ["NetExpenses"], "USD", quarter_only=True)
    assert kept == {"2023-09-30": 110.0}
    # any other field keeps the average, as before
    assert _extract_duration_series(_facts(earlier + [year]), ["NetExpenses"], "USD")["2024-12-31"] == pytest.approx(657.357 / 4)
    # and a quarter-only field is still split where the quarters are filed
    quarters = [{"start": "2024-01-01", "end": "2024-03-31", "val": 140.0}, {"start": "2024-04-01", "end": "2024-06-30", "val": 150.0},
                {"start": "2024-07-01", "end": "2024-09-30", "val": 178.0}]
    split = _extract_duration_series(_facts(quarters + [year]), ["NetExpenses"], "USD", quarter_only=True)
    assert split["2024-12-31"] == pytest.approx(657.357 - 468.0)


def test_net_expenses_is_the_quarter_only_field():
    from pipeline import extract_companyfacts
    specs = {}
    for value in vars(extract_companyfacts).values():
        if isinstance(value, dict) and "net_expenses" in value and isinstance(value["net_expenses"], dict):
            specs = value
    assert specs["net_expenses"].get("quarter_only") is True
    assert [name for name, spec in specs.items() if spec.get("quarter_only")] == ["net_expenses"]


def test_an_annual_figure_of_zero_is_not_turned_into_a_negative_quarter():
    # Ares 2023: interest expense of 139, 141 and 145 in the 10-Qs and a stored year figure of 0 (the 10-K's figure was
    # not captured). Annual less three quarters would publish -425.
    rows = [_income("1287750", "2023-03-31", 3, 600.0, 139.0), _income("1287750", "2023-06-30", 3, 630.0, 141.0),
            _income("1287750", "2023-09-30", 3, 650.0, 145.0), _income("1287750", "2023-12-31", 12, 653.5, 0.0)]
    out = _quarters(rows)
    assert out[("0001287750", "2023q4")] == (pytest.approx(4 * 653.5 - 1880.0), 0.0)
    # the stored figure is in fact 0.0125 (a year figure of 0.05): still far below three positive quarters
    rows[3] = _income("1287750", "2023-12-31", 12, 653.5, 0.0125)
    assert _quarters(rows)[("0001287750", "2023q4")][1] == 0.0125
    # a filed negative quarter stays possible: Ares incentive fees of 2, -29 and -37 with a year of -101
    rows = [_income("1287750", "2022-03-31", 3, 1.0, 2.0), _income("1287750", "2022-06-30", 3, 1.0, -29.0),
            _income("1287750", "2022-09-30", 3, 1.0, -37.0), _income("1287750", "2022-12-31", 12, 1.0, -25.25)]
    assert _quarters(rows)[("0001287750", "2022q4")][1] == pytest.approx(-37.0)
