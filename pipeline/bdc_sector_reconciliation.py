"""Reconcile BDC XBRL sector aggregates to unified BDC holdings totals.

The raw sector file is useful for public industry exposure only after it is
checked against the position-level holdings denominator.  This module writes
both a CIK-quarter status table and accepted reconciled sector rows.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from pipeline.config import (
    BDC_SECTOR_BREAKDOWN_FILE,
    BDC_SECTOR_BREAKDOWN_RECONCILED_FILE,
    BDC_SECTOR_RECONCILIATION_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

PASS_REL_TOLERANCE = 0.05
PASS_ABS_TOLERANCE = 1_000_000.0
SCALE_REL_TOLERANCE = 0.20

RECONCILIATION_COLUMNS = [
    "cik",
    "report_date",
    "holdings_fair_value",
    "raw_sector_fair_value",
    "absolute_delta",
    "relative_delta",
    "sector_row_count",
    "holdings_row_count",
    "reconciliation_status",
]

RECONCILED_BREAKDOWN_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "industry_sector",
    "investment_type",
    "gics_sub_industry",
    "raw_sector_fair_value",
    "reconciled_fair_value",
    "reconciliation_status",
    "scale_factor",
]


def _register_source(
    con: duckdb.DuckDBPyConnection,
    name: str,
    df: Optional[pd.DataFrame],
    path: Path,
    columns: list[str],
) -> bool:
    if df is not None:
        if df.empty:
            con.register(name, pd.DataFrame(columns=columns))
        else:
            con.register(name, df)
        return True
    if path.exists():
        con.execute(f"""
            CREATE TEMP VIEW {name} AS
            SELECT * FROM read_csv_auto('{path.as_posix()}', all_varchar=true)
        """)
        return True
    con.register(name, pd.DataFrame(columns=columns))
    return False


def reconcile_bdc_sector_breakdown(
    *,
    sector_df: Optional[pd.DataFrame] = None,
    holdings_df: Optional[pd.DataFrame] = None,
    write: bool = True,
    reconciliation_path: Path = BDC_SECTOR_RECONCILIATION_FILE,
    reconciled_breakdown_path: Path = BDC_SECTOR_BREAKDOWN_RECONCILED_FILE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build BDC sector reconciliation and accepted reconciled sector rows.

    Status policy:
    - PASS: raw sector FV within 5% of holdings FV, or absolute delta <= $1M
    - SCALE: raw sector FV within 20% of holdings FV; sector shares are scaled
    - FAIL_REVIEW: sector facts exist but outside tolerance
    - HOLDINGS_ONLY: BDC holdings exist but no sector facts
    - SECTOR_ONLY: sector facts exist but no unified holdings
    """
    con = duckdb.connect(":memory:")
    try:
        _register_source(
            con,
            "sector_raw",
            sector_df,
            BDC_SECTOR_BREAKDOWN_FILE,
            [
                "cik", "entity_name", "report_date", "industry_sector",
                "investment_type", "fair_value", "cost", "pct_of_net_assets",
                "gics_sub_industry",
            ],
        )
        _register_source(
            con,
            "holdings_raw",
            holdings_df,
            UNIFIED_HOLDINGS_FILE,
            [
                "source", "cik", "report_date", "issuer_name", "fair_value",
            ],
        )

        reconciliation = con.execute(f"""
            WITH sector_totals AS (
                SELECT
                    CAST(cik AS VARCHAR) AS cik,
                    CAST(report_date AS VARCHAR) AS report_date,
                    SUM(TRY_CAST(fair_value AS DOUBLE)) AS raw_sector_fair_value,
                    COUNT(*) AS sector_row_count
                FROM sector_raw
                WHERE TRY_CAST(fair_value AS DOUBLE) > 0
                GROUP BY CAST(cik AS VARCHAR), CAST(report_date AS VARCHAR)
            ),
            holdings_totals AS (
                SELECT
                    CAST(cik AS VARCHAR) AS cik,
                    CAST(report_date AS VARCHAR) AS report_date,
                    SUM(TRY_CAST(fair_value AS DOUBLE)) AS holdings_fair_value,
                    COUNT(*) AS holdings_row_count
                FROM holdings_raw
                WHERE source = 'bdc'
                  AND TRY_CAST(fair_value AS DOUBLE) > 0
                GROUP BY CAST(cik AS VARCHAR), CAST(report_date AS VARCHAR)
            ),
            joined AS (
                SELECT
                    COALESCE(CAST(h.cik AS VARCHAR), CAST(s.cik AS VARCHAR)) AS cik,
                    COALESCE(
                        CAST(h.report_date AS VARCHAR),
                        CAST(s.report_date AS VARCHAR)
                    ) AS report_date,
                    h.holdings_fair_value,
                    s.raw_sector_fair_value,
                    ABS(
                        COALESCE(s.raw_sector_fair_value, 0)
                        - COALESCE(h.holdings_fair_value, 0)
                    ) AS absolute_delta,
                    CASE
                        WHEN h.holdings_fair_value > 0
                        THEN ABS(s.raw_sector_fair_value - h.holdings_fair_value)
                             / h.holdings_fair_value
                    END AS relative_delta,
                    COALESCE(s.sector_row_count, 0) AS sector_row_count,
                    COALESCE(h.holdings_row_count, 0) AS holdings_row_count
                FROM holdings_totals h
                FULL OUTER JOIN sector_totals s
                  ON h.cik = s.cik AND h.report_date = s.report_date
            )
            SELECT
                cik,
                report_date,
                holdings_fair_value,
                raw_sector_fair_value,
                absolute_delta,
                relative_delta,
                sector_row_count,
                holdings_row_count,
                CASE
                    WHEN holdings_fair_value IS NULL THEN 'SECTOR_ONLY'
                    WHEN raw_sector_fair_value IS NULL THEN 'HOLDINGS_ONLY'
                    WHEN absolute_delta <= {PASS_ABS_TOLERANCE}
                      OR relative_delta <= {PASS_REL_TOLERANCE} THEN 'PASS'
                    WHEN relative_delta <= {SCALE_REL_TOLERANCE} THEN 'SCALE'
                    ELSE 'FAIL_REVIEW'
                END AS reconciliation_status
            FROM joined
            ORDER BY cik, report_date
        """).df()

        con.register("reconciliation", reconciliation)
        reconciled = con.execute("""
            SELECT
                s.cik,
                s.entity_name,
                s.report_date,
                s.industry_sector,
                COALESCE(s.investment_type, '') AS investment_type,
                COALESCE(s.gics_sub_industry, 'Other') AS gics_sub_industry,
                TRY_CAST(s.fair_value AS DOUBLE) AS raw_sector_fair_value,
                CASE
                    WHEN r.reconciliation_status = 'PASS'
                    THEN TRY_CAST(s.fair_value AS DOUBLE)
                    WHEN r.reconciliation_status = 'SCALE'
                    THEN TRY_CAST(s.fair_value AS DOUBLE)
                         / NULLIF(r.raw_sector_fair_value, 0)
                         * r.holdings_fair_value
                END AS reconciled_fair_value,
                r.reconciliation_status,
                CASE
                    WHEN r.reconciliation_status = 'PASS' THEN 1.0
                    WHEN r.reconciliation_status = 'SCALE'
                    THEN r.holdings_fair_value / NULLIF(r.raw_sector_fair_value, 0)
                END AS scale_factor
            FROM sector_raw s
            JOIN reconciliation r
              ON s.cik = r.cik AND s.report_date = r.report_date
            WHERE r.reconciliation_status IN ('PASS', 'SCALE')
              AND TRY_CAST(s.fair_value AS DOUBLE) > 0
            ORDER BY s.cik, s.report_date, reconciled_fair_value DESC NULLS LAST
        """).df()

        for col in RECONCILIATION_COLUMNS:
            if col not in reconciliation.columns:
                reconciliation[col] = None
        for col in RECONCILED_BREAKDOWN_COLUMNS:
            if col not in reconciled.columns:
                reconciled[col] = None
        reconciliation = reconciliation[RECONCILIATION_COLUMNS]
        reconciled = reconciled[RECONCILED_BREAKDOWN_COLUMNS]

        if write:
            reconciliation_path.parent.mkdir(parents=True, exist_ok=True)
            reconciled_breakdown_path.parent.mkdir(parents=True, exist_ok=True)
            reconciliation.to_csv(reconciliation_path, index=False)
            reconciled.to_csv(reconciled_breakdown_path, index=False)
            logger.info(
                "BDC sector reconciliation: %d CIK-quarters, %d accepted rows",
                len(reconciliation),
                len(reconciled),
            )

        return reconciliation, reconciled
    finally:
        con.close()
