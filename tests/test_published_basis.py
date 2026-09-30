"""The published basis: one numerator for the headline and every FV gate (spec section 1).

Owner ruling 2026-09-30: rows with accounting_record_class = 'underlying_schedule' (the
underlying positions of a BDC's joint ventures) are excluded; everything else still counts.
"""
import duckdb
import pandas as pd

from pipeline.published_basis import (
    PUBLISHED_ROWS_WHERE_SQL, published_fv_by_quarter, published_fv_mask,
    published_fv_sum_sql, published_rows_csv_sql,
)


def _frame():
    # cash, subsidiary-axis parent rows, added (no accession), unpadded cik, NULL dims,
    # comparative period: ALL of them count. A NULL fair_value contributes nothing.
    # The one underlying_schedule row (JV look-through) is the only excluded row.
    return pd.DataFrame([
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 1815.0,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 0,
         "accounting_record_class": "parent_schedule"},
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 406.5,
         "bdc_dimensions_raw": "nonconsolidatedsubsidiaryaxis=SLP", "asset_category": "LOAN",
         "is_subsidiary": 1, "accounting_record_class": "parent_schedule"},
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 20.0,
         "bdc_dimensions_raw": "cashandcashequivalentsaxis=MMF", "asset_category": "CASH",
         "is_subsidiary": None, "accounting_record_class": "parent_schedule"},
        {"cik": "1899017", "report_date": "2026-03-31", "fair_value": 5.0,
         "bdc_dimensions_raw": None, "asset_category": "LOAN", "is_subsidiary": 0,
         "accounting_record_class": "parent_schedule"},
        {"cik": "0001899017", "report_date": "2026-03-31 00:00:00", "fair_value": None,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 0,
         "accounting_record_class": "parent_schedule"},
        {"cik": "0001899017", "report_date": "2025-12-31", "fair_value": 1630.1,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 0,
         "accounting_record_class": "parent_schedule"},
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 999.0,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 1,
         "accounting_record_class": "underlying_schedule"},
    ])


def test_sql_and_pandas_agree_and_exclude_only_underlying_schedule():
    df = _frame()
    con = duckdb.connect()
    con.register("u", df)
    rows = con.execute(published_fv_sum_sql("u")).fetchall()
    got = {(c, d): (v, n) for c, d, v, n in rows}
    assert got == {("0001899017", "2026-03-31"): (2246.5, 5),
                   ("0001899017", "2025-12-31"): (1630.1, 1)}
    assert published_fv_by_quarter(df) == {"2026-03-31": 2246.5, "2025-12-31": 1630.1}


def test_sql_where_and_timestamp_report_date():
    df = _frame()
    con = duckdb.connect()
    con.register("u", df)
    rows = con.execute(published_fv_sum_sql("u", "report_date LIKE '2025%'")).fetchall()
    assert rows == [("0001899017", "2025-12-31", 1630.1, 1)]


def test_sql_null_and_other_record_classes_are_kept():
    df = _frame()
    df.loc[0, "accounting_record_class"] = None
    df.loc[1, "accounting_record_class"] = "unresolved_underlying_schedule"
    con = duckdb.connect()
    con.register("u", df)
    rows = con.execute(published_fv_sum_sql("u", "report_date LIKE '2026%'")).fetchall()
    assert rows == [("0001899017", "2026-03-31", 2246.5, 5)]
    assert published_fv_mask(df).tolist() == [True] * 6 + [False]


def test_mask_excludes_only_underlying_schedule_and_empty_frames():
    df = _frame()
    mask = published_fv_mask(df)
    assert len(mask) == len(df)
    assert mask.tolist() == [True] * 6 + [False]
    assert published_fv_by_quarter(pd.DataFrame()) == {}
    assert published_fv_by_quarter(pd.DataFrame({"cik": []})) == {}


def test_frame_without_record_class_column_is_fully_included():
    df = _frame().drop(columns=["accounting_record_class"])
    assert published_fv_mask(df).all()
    assert published_fv_by_quarter(df) == {"2026-03-31": 3245.5, "2025-12-31": 1630.1}


def test_published_rows_csv_sql_filters_a_csv(tmp_path):
    path = tmp_path / "private_markets_holdings.csv"
    _frame().to_csv(path, index=False)
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT count(*), sum(TRY_CAST(fair_value AS DOUBLE)) FROM {published_rows_csv_sql(path)}"
    ).fetchone()
    assert rows[0] == 6 and abs(rows[1] - 3876.6) < 1e-6
    kinds = con.execute(
        f"SELECT DISTINCT accounting_record_class FROM {published_rows_csv_sql(path)}"
    ).fetchall()
    assert kinds == [("parent_schedule",)]
    assert "underlying_schedule" in PUBLISHED_ROWS_WHERE_SQL
