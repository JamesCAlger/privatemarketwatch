"""The published basis: the ONE row set the public headline and every FV gate sum.

Spec (docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md, s.1):

    published_fv(cik, quarter) = SUM(fair_value) over all unified rows with that 10-digit cik
    and report_date, with no category, dimension, or subsidiary filter.

Until 2026-09-07 four gate implementations each excluded CASH and is_subsidiary=1 rows (with
per-CIK carve-outs) while the headline excluded nothing; the rows that inflated the headline
were exactly the rows the gates dropped, so nine of twelve Q1-2026 defect funds reconciled to
0.000% against a headline that was $4.09B too high. This module is the single definition;
callers must not add filters. ASCII-only.
"""
from __future__ import annotations

import pandas as pd

# report_date may be VARCHAR, DATE, or TIMESTAMP ('2025-12-31 00:00:00' from typed parquet).
REPORT_DATE_KEY_SQL = "substr(CAST(report_date AS VARCHAR), 1, 10)"
CIK10_SQL = "lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')"


def published_fv_sum_sql(table_expr: str, where: str = "TRUE") -> str:
    """SELECT cik, report_date, value_sum, n_rows FROM <table_expr> WHERE <where> GROUP BY 1,2.
    n_rows counts ALL rows in the group (a NULL fair_value contributes 0 to value_sum but
    still counts as a row -- it is a published row with an unknown value, not an excluded one)."""
    return f"""
        SELECT {CIK10_SQL} AS cik,
               {REPORT_DATE_KEY_SQL} AS report_date,
               sum(TRY_CAST(fair_value AS DOUBLE)) AS value_sum,
               count(*) AS n_rows
        FROM {table_expr}
        WHERE ({where})
        GROUP BY 1, 2
    """


def published_fv_mask(df: pd.DataFrame) -> pd.Series:
    """Rows that count: all of them. Exists so mask-taking callers have one named source."""
    return pd.Series(True, index=df.index)


def published_fv_by_quarter(df: pd.DataFrame) -> dict[str, float]:
    """{report_date (10 chars) -> sum(fair_value)} for one CIK's frame; no filters."""
    if df is None or len(df) == 0 or "report_date" not in df.columns:
        return {}
    fv = pd.to_numeric(df.get("fair_value"), errors="coerce").fillna(0.0)
    key = df["report_date"].astype(str).str.slice(0, 10)
    return {str(k): float(v) for k, v in fv.groupby(key).sum().items()}
