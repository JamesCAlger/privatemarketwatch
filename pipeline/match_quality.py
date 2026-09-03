"""Deterministic match-quality metrics over unified holdings + position edges.

Signals, not truth: these metrics baseline chain behavior so later changes
(Tier E repair, agent corrections) can be gated on regression. The gold set
built by scripts/match_gold/ is the truth layer.

All heavy transforms are DuckDB SQL; functions accept DataFrames so tests
never touch production paths.
"""
from __future__ import annotations

import logging

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

METRIC_COLUMNS = ["metric", "scope_type", "scope", "numerator", "denominator", "value"]

_BDC_POSITIVE = """
    SELECT cik, report_date, issuer_name, row_id, position_id,
           TRY_CAST(fair_value AS DOUBLE) AS fv,
           index_classification,
           TRY_CAST(interest_rate AS DOUBLE) AS rate,
           maturity_date
    FROM h
    WHERE source = 'bdc'
      AND TRY_CAST(fair_value AS DOUBLE) > 0
      AND position_id IS NOT NULL
"""


def _con(holdings_df: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.register("h", holdings_df)
    return con


def _finish(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    df = df.copy()
    df["metric"] = metric
    df["value"] = df.apply(
        lambda r: (r["numerator"] / r["denominator"]) if r["denominator"] else 0.0,
        axis=1,
    )  # small frame only (one row per scope)
    return df[METRIC_COLUMNS].sort_values(["metric", "scope_type", "scope"]).reset_index(drop=True)


def chain_continuity(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """Share of positive-FV BDC rows in non-terminal quarters whose position_id
    reappears in a later quarter of the same CIK."""
    con = _con(holdings_df)
    per_cik = con.execute(f"""
        WITH rows_q AS ({_BDC_POSITIVE}),
        maxq AS (SELECT cik, MAX(report_date) AS max_date FROM rows_q GROUP BY cik),
        eligible AS (
            SELECT r.* FROM rows_q r JOIN maxq m
              ON r.cik = m.cik AND r.report_date < m.max_date
        ),
        continued AS (
            SELECT DISTINCT e.row_id FROM eligible e
            JOIN rows_q later
              ON later.cik = e.cik AND later.position_id = e.position_id
             AND later.report_date > e.report_date
        )
        SELECT e.cik AS scope,
               COUNT(c.row_id) AS numerator,
               COUNT(*) AS denominator
        FROM eligible e LEFT JOIN continued c ON e.row_id = c.row_id
        GROUP BY e.cik ORDER BY e.cik
    """).df()
    per_cik["scope_type"] = "cik"
    total = pd.DataFrame([{
        "scope": "ALL", "scope_type": "ALL",
        "numerator": int(per_cik["numerator"].sum()),
        "denominator": int(per_cik["denominator"].sum()),
    }])
    return _finish(pd.concat([total, per_cik], ignore_index=True), "chain_continuity_rate")


def singleton_decomposition(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """Classify singleton position_ids (appear exactly once, BDC source):
    terminal_quarter / first_quarter / zero_or_null_fv / negative_fv /
    interior_suspicious. Priority order as listed: a zero-FV terminal row
    counts as terminal_quarter? No -- data-quality classes win: zero/negative
    FV first, then boundary quarters, then interior_suspicious."""
    con = _con(holdings_df)
    classes = con.execute("""
        WITH bdc AS (
            SELECT cik, report_date, position_id, row_id,
                   TRY_CAST(fair_value AS DOUBLE) AS fv
            FROM h WHERE source = 'bdc' AND position_id IS NOT NULL
        ),
        pid_counts AS (
            SELECT position_id FROM bdc GROUP BY position_id HAVING COUNT(*) = 1
        ),
        bounds AS (
            SELECT cik, MIN(report_date) AS min_date, MAX(report_date) AS max_date
            FROM bdc GROUP BY cik
        ),
        singles AS (
            SELECT b.*, bd.min_date, bd.max_date
            FROM bdc b
            JOIN pid_counts p ON b.position_id = p.position_id
            JOIN bounds bd ON b.cik = bd.cik
        )
        SELECT CASE
                 WHEN fv IS NULL OR fv = 0 THEN 'zero_or_null_fv'
                 WHEN fv < 0 THEN 'negative_fv'
                 WHEN report_date = max_date THEN 'terminal_quarter'
                 WHEN report_date = min_date THEN 'first_quarter'
                 ELSE 'interior_suspicious'
               END AS scope,
               COUNT(*) AS numerator
        FROM singles GROUP BY 1 ORDER BY 1
    """).df()
    classes["scope_type"] = "singleton_class"
    classes["denominator"] = int(classes["numerator"].sum())
    return _finish(classes, "singleton_decomposition")
