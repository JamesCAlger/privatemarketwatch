"""The published basis: one numerator for the headline and every FV gate (spec section 1)."""
import duckdb
import pandas as pd

from pipeline.published_basis import (
    published_fv_by_quarter, published_fv_mask, published_fv_sum_sql,
)


def _frame():
    # cash, subsidiary, added (no accession), unpadded cik, NULL dims, comparative period:
    # ALL of them count. Only a NULL fair_value contributes nothing.
    return pd.DataFrame([
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 1815.0,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 0},
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 406.5,
         "bdc_dimensions_raw": "nonconsolidatedsubsidiaryaxis=SLP", "asset_category": "LOAN",
         "is_subsidiary": 1},
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 20.0,
         "bdc_dimensions_raw": "cashandcashequivalentsaxis=MMF", "asset_category": "CASH",
         "is_subsidiary": None},
        {"cik": "1899017", "report_date": "2026-03-31", "fair_value": 5.0,
         "bdc_dimensions_raw": None, "asset_category": "LOAN", "is_subsidiary": 0},
        {"cik": "0001899017", "report_date": "2026-03-31 00:00:00", "fair_value": None,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 0},
        {"cik": "0001899017", "report_date": "2025-12-31", "fair_value": 1630.1,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 0},
    ])


def test_sql_and_pandas_agree_and_include_everything():
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


def test_mask_is_all_true_and_empty_frames():
    df = _frame()
    assert published_fv_mask(df).all() and len(published_fv_mask(df)) == len(df)
    assert published_fv_by_quarter(pd.DataFrame()) == {}
    assert published_fv_by_quarter(pd.DataFrame({"cik": []})) == {}
