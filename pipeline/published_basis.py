"""The published basis: the ONE row set the public headline and every FV gate sum.

Spec (docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md, s.1):

    published_fv(cik, quarter) = SUM(fair_value) over all unified rows with that 10-digit cik
    and report_date, with no category, dimension, or subsidiary filter.

History (v3, 2026-09-07): until then four gate implementations each excluded CASH and
is_subsidiary=1 rows (with per-CIK carve-outs) while the headline excluded nothing; the rows
that inflated the headline were exactly the rows the gates dropped, so nine of twelve Q1-2026
defect funds reconciled to 0.000% against a headline that was $4.09B too high. The fix was a
single definition with no category, dimension, or subsidiary filter.

Owner ruling (2026-09-30): the published basis EXCLUDES rows whose accounting_record_class is
exactly 'underlying_schedule', for BOTH the public headline and every FV gate. Those rows are
the underlying positions of a BDC's joint ventures (for example BCRED's Emerald and Verdelite
JVs, 722 rows / $7.7B in Q1-2026). The BDC's own exposure is its JV interest line on the parent
schedule, so counting the look-through rows as well double counts. Only the exact value
'underlying_schedule' is excluded: 'parent_schedule', NULL/blank and any other value
(including 'unresolved_underlying_schedule') still count. is_subsidiary is derived from the
same scope and is NOT the key. PUBLISHED_ROWS_WHERE_SQL is the single predicate; callers must
use it (or the helpers below) and must not add other filters. ASCII-only.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# report_date may be VARCHAR, DATE, or TIMESTAMP ('2025-12-31 00:00:00' from typed parquet).
REPORT_DATE_KEY_SQL = "substr(CAST(report_date AS VARCHAR), 1, 10)"
CIK10_SQL = "lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')"

# The one row predicate of the published basis (owner ruling 2026-09-30).
UNDERLYING_SCHEDULE_CLASS = "underlying_schedule"
PUBLISHED_ROWS_WHERE_SQL = "coalesce(accounting_record_class, '') <> 'underlying_schedule'"


def published_fv_sum_sql(table_expr: str, where: str = "TRUE") -> str:
    """SELECT cik, report_date, value_sum, n_rows FROM <table_expr>
    WHERE (<where>) AND (PUBLISHED_ROWS_WHERE_SQL) GROUP BY 1,2.

    n_rows counts ALL published rows in the group (a NULL fair_value contributes 0 to value_sum
    but still counts as a row -- it is a published row with an unknown value, not an excluded
    one). <table_expr> MUST expose an accounting_record_class column; without it the SQL fails
    with a binder error. That is intended: the column is part of the unified holdings artifact
    contract, and a missing column must fail loudly rather than silently re-include JV rows."""
    return f"""
        SELECT {CIK10_SQL} AS cik,
               {REPORT_DATE_KEY_SQL} AS report_date,
               sum(TRY_CAST(fair_value AS DOUBLE)) AS value_sum,
               count(*) AS n_rows
        FROM {table_expr}
        WHERE ({where}) AND ({PUBLISHED_ROWS_WHERE_SQL})
        GROUP BY 1, 2
    """


def published_rows_csv_sql(path) -> str:
    """A parenthesised subquery over a holdings CSV (all_varchar) that keeps only published
    rows. Usable anywhere a table expression is, e.g. f"FROM {published_rows_csv_sql(p)}"."""
    posix = Path(path).as_posix()
    return (f"(SELECT * FROM read_csv_auto('{posix}', all_varchar=true) "
            f"WHERE {PUBLISHED_ROWS_WHERE_SQL})")


def published_fv_mask(df: pd.DataFrame) -> pd.Series:
    """True for every published row: all rows except accounting_record_class ==
    'underlying_schedule'. A frame without that column keeps all rows."""
    if "accounting_record_class" not in df.columns:
        return pd.Series(True, index=df.index)
    cls = df["accounting_record_class"].astype("string").fillna("")
    return (cls != UNDERLYING_SCHEDULE_CLASS).astype(bool)


def published_fv_by_quarter(df: pd.DataFrame) -> dict[str, float]:
    """{report_date (10 chars) -> sum(fair_value)} over one CIK's published rows."""
    if df is None or len(df) == 0 or "report_date" not in df.columns:
        return {}
    df = df[published_fv_mask(df)]
    if len(df) == 0:
        return {}
    fv = pd.to_numeric(df.get("fair_value"), errors="coerce").fillna(0.0)
    key = df["report_date"].astype(str).str.slice(0, 10)
    return {str(k): float(v) for k, v in fv.groupby(key).sum().items()}
