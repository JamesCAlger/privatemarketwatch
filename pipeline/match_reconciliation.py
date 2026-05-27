"""Deterministic coverage diagnostics for quarter-to-quarter position matching."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from pipeline import config

logger = logging.getLogger(__name__)

COVERAGE_COLUMNS = [
    "source", "quarter", "cik", "index_classification",
    "eligible_backward_rows", "any_span_matched_rows", "short_span_matched_rows",
    "eligible_backward_fv", "any_span_matched_fv", "short_span_matched_fv",
    "any_span_row_match_rate", "short_span_row_match_rate",
    "any_span_fv_match_rate", "short_span_fv_match_rate",
]

UNMATCHED_SUMMARY_COLUMNS = [
    "source", "quarter", "cik", "index_classification",
    "unmatched_rows", "unmatched_fv", "residual_buckets",
]

RESIDUAL_COLUMNS = [
    "source", "quarter", "cik", "entity_name", "report_date",
    "issuer_name", "position_id", "index_classification", "fair_value",
    "cusip", "bdc_investment_identifier", "instrument_description",
    "residual_bucket",
]


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = df.copy()
    for col in columns:
        if col not in result.columns:
            result[col] = ""
    return result


def _empty_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.DataFrame(columns=COVERAGE_COLUMNS),
        pd.DataFrame(columns=UNMATCHED_SUMMARY_COLUMNS),
        pd.DataFrame(columns=RESIDUAL_COLUMNS),
    )


def build_position_match_reconciliation(
    holdings_df: Optional[pd.DataFrame] = None,
    matches_df: Optional[pd.DataFrame] = None,
    *,
    write: bool = True,
    coverage_path: str | Path | None = None,
    unmatched_summary_path: str | Path | None = None,
    residuals_path: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build match coverage and unmatched residual diagnostics.

    Coverage is measured on current-quarter holding rows for CIK/source
    histories that have at least one earlier holding row. A row is covered
    when it appears as the end side of a position match. ``short`` coverage
    is restricted to matches with ``span_months <= 4``.
    """
    if holdings_df is None:
        if not config.UNIFIED_HOLDINGS_FILE.exists():
            frames = _empty_frames()
            if write:
                _write_frames(*frames, coverage_path, unmatched_summary_path, residuals_path)
            return frames
        holdings_df = pd.read_csv(config.UNIFIED_HOLDINGS_FILE, dtype=str)

    if matches_df is None:
        if not config.POSITION_MATCHES_FILE.exists():
            matches_df = pd.DataFrame()
        else:
            matches_df = pd.read_csv(config.POSITION_MATCHES_FILE, dtype=str)

    if holdings_df.empty:
        frames = _empty_frames()
        if write:
            _write_frames(*frames, coverage_path, unmatched_summary_path, residuals_path)
        return frames

    holdings_cols = [
        "source", "quarter", "cik", "entity_name", "report_date",
        "issuer_name", "position_id", "index_classification", "fair_value",
        "cusip", "bdc_investment_identifier", "instrument_description",
    ]
    match_cols = [
        "cik", "source", "end_quarter", "end_report_date", "end_issuer_name",
        "end_fair_value", "position_id", "span_months",
    ]
    holdings = _ensure_columns(holdings_df, holdings_cols)
    matches = _ensure_columns(matches_df, match_cols)

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    con.register("holdings_in", holdings)
    con.register("matches_in", matches)

    con.execute(
        """
        CREATE TEMP TABLE holdings_base AS
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY
                    CAST(source AS VARCHAR), CAST(cik AS VARCHAR),
                    CAST(report_date AS VARCHAR), CAST(issuer_name AS VARCHAR),
                    CAST(fair_value AS VARCHAR), CAST(position_id AS VARCHAR)
            ) AS h_id,
            CAST(source AS VARCHAR) AS source,
            CAST(quarter AS VARCHAR) AS quarter,
            CAST(cik AS VARCHAR) AS cik,
            CAST(entity_name AS VARCHAR) AS entity_name,
            CAST(report_date AS VARCHAR) AS report_date,
            CAST(issuer_name AS VARCHAR) AS issuer_name,
            CAST(position_id AS VARCHAR) AS position_id,
            CAST(index_classification AS VARCHAR) AS index_classification,
            TRY_CAST(fair_value AS DOUBLE) AS fv,
            CAST(cusip AS VARCHAR) AS cusip,
            CAST(bdc_investment_identifier AS VARCHAR) AS bdc_investment_identifier,
            CAST(instrument_description AS VARCHAR) AS instrument_description,
            LOWER(TRIM(CAST(issuer_name AS VARCHAR))) AS norm_issuer,
            COALESCE(NULLIF(CAST(quarter AS VARCHAR), ''),
                CASE WHEN TRY_CAST(report_date AS DATE) IS NOT NULL
                    THEN CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                         || 'q' || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                    ELSE CAST(report_date AS VARCHAR)
                END
            ) AS q
        FROM holdings_in
        WHERE COALESCE(TRY_CAST(fair_value AS DOUBLE), 0) <> 0
        """
    )

    con.execute(
        """
        CREATE TEMP TABLE matched_end AS
        WITH candidates AS (
            SELECT
                h.h_id,
                MAX(1) AS any_span_matched,
                MAX(CASE WHEN TRY_CAST(m.span_months AS DOUBLE) <= 4 THEN 1 ELSE 0 END)
                    AS short_span_matched
            FROM holdings_base h
            JOIN matches_in m
              ON h.cik = CAST(m.cik AS VARCHAR)
             AND h.source = CAST(m.source AS VARCHAR)
             AND h.report_date = CAST(m.end_report_date AS VARCHAR)
             AND (
                (COALESCE(h.position_id, '') <> ''
                 AND h.position_id = CAST(m.position_id AS VARCHAR))
                OR (
                    h.norm_issuer = LOWER(TRIM(CAST(m.end_issuer_name AS VARCHAR)))
                    AND ABS(COALESCE(h.fv, 0) - COALESCE(TRY_CAST(m.end_fair_value AS DOUBLE), 0))
                        <= GREATEST(1.0, ABS(COALESCE(h.fv, 0)) * 0.01)
                )
             )
            GROUP BY h.h_id
        )
        SELECT * FROM candidates
        """
    )

    con.execute(
        """
        CREATE TEMP TABLE eligible AS
        WITH enriched AS (
            SELECT
                h.*,
                COALESCE(me.any_span_matched, 0) AS any_span_matched,
                COALESCE(me.short_span_matched, 0) AS short_span_matched,
                EXISTS (
                    SELECT 1 FROM holdings_base p
                    WHERE p.cik = h.cik
                      AND p.source = h.source
                      AND p.report_date < h.report_date
                ) AS prior_exists
            FROM holdings_base h
            LEFT JOIN matched_end me USING (h_id)
        )
        SELECT * FROM enriched WHERE prior_exists
        """
    )

    coverage = con.execute(
        """
        SELECT
            source, q AS quarter, cik, index_classification,
            COUNT(*) AS eligible_backward_rows,
            SUM(any_span_matched) AS any_span_matched_rows,
            SUM(short_span_matched) AS short_span_matched_rows,
            SUM(ABS(COALESCE(fv, 0))) AS eligible_backward_fv,
            SUM(CASE WHEN any_span_matched = 1 THEN ABS(COALESCE(fv, 0)) ELSE 0 END)
                AS any_span_matched_fv,
            SUM(CASE WHEN short_span_matched = 1 THEN ABS(COALESCE(fv, 0)) ELSE 0 END)
                AS short_span_matched_fv,
            SUM(any_span_matched)::DOUBLE / NULLIF(COUNT(*), 0)
                AS any_span_row_match_rate,
            SUM(short_span_matched)::DOUBLE / NULLIF(COUNT(*), 0)
                AS short_span_row_match_rate,
            SUM(CASE WHEN any_span_matched = 1 THEN ABS(COALESCE(fv, 0)) ELSE 0 END)
                / NULLIF(SUM(ABS(COALESCE(fv, 0))), 0) AS any_span_fv_match_rate,
            SUM(CASE WHEN short_span_matched = 1 THEN ABS(COALESCE(fv, 0)) ELSE 0 END)
                / NULLIF(SUM(ABS(COALESCE(fv, 0))), 0) AS short_span_fv_match_rate
        FROM eligible
        GROUP BY source, q, cik, index_classification
        ORDER BY source, q, cik, index_classification
        """
    ).fetchdf()

    residuals = con.execute(
        """
        WITH issuer_counts AS (
            SELECT cik, source, report_date, norm_issuer, COUNT(*) AS n
            FROM holdings_base
            WHERE norm_issuer <> ''
            GROUP BY cik, source, report_date, norm_issuer
        ),
        residual_base AS (
            SELECT
                e.*,
                COALESCE(ic.n, 0) AS current_issuer_count,
                (
                    SELECT MAX(ip.n)
                    FROM issuer_counts ip
                    WHERE ip.cik = e.cik
                      AND ip.source = e.source
                      AND ip.norm_issuer = e.norm_issuer
                      AND ip.report_date < e.report_date
                ) AS prior_issuer_count,
                EXISTS (
                    SELECT 1 FROM holdings_base p
                    WHERE p.cik = e.cik
                      AND p.source = e.source
                      AND p.report_date < e.report_date
                      AND COALESCE(p.cusip, '') <> ''
                      AND p.cusip = e.cusip
                ) AS cusip_existed_prior,
                EXISTS (
                    SELECT 1 FROM holdings_base p
                    WHERE p.cik = e.cik
                      AND p.source = e.source
                      AND p.report_date < e.report_date
                      AND p.norm_issuer <> ''
                      AND p.norm_issuer = e.norm_issuer
                ) AS issuer_existed_prior
            FROM eligible e
            LEFT JOIN issuer_counts ic
              ON e.cik = ic.cik
             AND e.source = ic.source
             AND e.report_date = ic.report_date
             AND e.norm_issuer = ic.norm_issuer
            WHERE e.any_span_matched = 0
        )
        SELECT
            source, q AS quarter, cik, entity_name, report_date,
            issuer_name, position_id, index_classification, fv AS fair_value,
            cusip, bdc_investment_identifier, instrument_description,
            CASE
                WHEN LOWER(source) = 'bdc'
                     AND COALESCE(bdc_investment_identifier, '') = ''
                    THEN 'parser_failure'
                WHEN COALESCE(issuer_name, '') = ''
                     AND COALESCE(cusip, '') = ''
                     AND COALESCE(bdc_investment_identifier, '') = ''
                     AND COALESCE(instrument_description, '') = ''
                    THEN 'missing_instrument_data'
                WHEN COALESCE(current_issuer_count, 0) > 1
                     OR COALESCE(prior_issuer_count, 0) > 1
                    THEN 'multi_tranche_ambiguity'
                WHEN cusip_existed_prior
                    THEN 'cusip_existed_unmatched'
                WHEN issuer_existed_prior
                    THEN 'same_issuer_existed_unmatched'
                ELSE 'likely_new_or_exit'
            END AS residual_bucket
        FROM residual_base
        ORDER BY ABS(COALESCE(fv, 0)) DESC, source, quarter, cik, issuer_name
        """
    ).fetchdf()

    con.register("residuals", residuals)
    unmatched_summary = con.execute(
        """
        SELECT
            source, quarter, cik, index_classification,
            COUNT(*) AS unmatched_rows,
            SUM(ABS(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0))) AS unmatched_fv,
            STRING_AGG(DISTINCT residual_bucket, ';' ORDER BY residual_bucket)
                AS residual_buckets
        FROM residuals
        GROUP BY source, quarter, cik, index_classification
        ORDER BY unmatched_fv DESC, unmatched_rows DESC, source, quarter, cik
        """
    ).fetchdf()
    con.close()

    for col in COVERAGE_COLUMNS:
        if col not in coverage.columns:
            coverage[col] = None
    for col in UNMATCHED_SUMMARY_COLUMNS:
        if col not in unmatched_summary.columns:
            unmatched_summary[col] = None
    for col in RESIDUAL_COLUMNS:
        if col not in residuals.columns:
            residuals[col] = None

    coverage = coverage[COVERAGE_COLUMNS]
    unmatched_summary = unmatched_summary[UNMATCHED_SUMMARY_COLUMNS]
    residuals = residuals[RESIDUAL_COLUMNS]

    if write:
        _write_frames(coverage, unmatched_summary, residuals, coverage_path,
                      unmatched_summary_path, residuals_path)

    logger.info(
        "Position match reconciliation: %d coverage rows, %d unmatched groups, %d residual rows",
        len(coverage),
        len(unmatched_summary),
        len(residuals),
    )
    return coverage, unmatched_summary, residuals


def _write_frames(
    coverage: pd.DataFrame,
    unmatched_summary: pd.DataFrame,
    residuals: pd.DataFrame,
    coverage_path: str | Path | None,
    unmatched_summary_path: str | Path | None,
    residuals_path: str | Path | None,
) -> None:
    coverage_out = Path(coverage_path or config.POSITION_MATCH_COVERAGE_FILE)
    unmatched_out = Path(unmatched_summary_path or config.POSITION_MATCH_UNMATCHED_SUMMARY_FILE)
    residuals_out = Path(residuals_path or config.POSITION_MATCH_RESIDUALS_FILE)
    for path, df in [
        (coverage_out, coverage),
        (unmatched_out, unmatched_summary),
        (residuals_out, residuals),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
