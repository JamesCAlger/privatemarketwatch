"""Diagnostic-only position purity checks for unified holdings.

This module measures candidate subtotal leakage, duplicate dimension paths,
and comparative-period rows without mutating holdings or deciding exclusions.
The output is intended for validation review while source reconciliation
continues to define the stronger data-quality contract.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from pipeline.bdc_identifier import _sql_is_bdc_aggregate
from pipeline.config import BDC_HOLDINGS_FILE

logger = logging.getLogger(__name__)

DIAGNOSTIC_COLUMNS = [
    "issue_family", "issue_type", "source", "cik", "entity_name",
    "report_date", "period", "accession_number", "row_key",
    "issuer_name", "instrument_description", "bdc_investment_identifier",
    "bdc_dimensions_raw", "fair_value", "cost", "principal_amount",
    "shares_held", "duplicate_group_id", "dimension_path_count",
    "evidence", "recommended_action",
]

METRIC_COLUMNS = [
    "source", "cik", "entity_name", "report_date", "quarter",
    "row_count", "subtotal_candidate_rows", "subtotal_candidate_fv",
    "duplicate_dimension_candidate_rows", "duplicate_dimension_candidate_fv",
    "comparative_period_rows", "comparative_period_fv",
    "issue_rows", "affected_fair_value",
]


def _empty_diagnostics() -> pd.DataFrame:
    return pd.DataFrame(columns=DIAGNOSTIC_COLUMNS)


def _empty_metrics() -> pd.DataFrame:
    return pd.DataFrame(columns=METRIC_COLUMNS)


def _prepare_holdings(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    needed = [
        "source", "cik", "entity_name", "report_date", "accession_number",
        "issuer_name", "instrument_description", "bdc_investment_identifier",
        "bdc_dimensions_raw", "fair_value", "cost", "principal_amount",
        "shares_held", "cusip", "isin",
    ]
    for col in needed:
        if col not in prepared.columns:
            prepared[col] = ""
    if "period" not in prepared.columns:
        prepared["period"] = ""
    prepared["_row_key"] = range(len(prepared))
    return prepared


def _load_bdc_source(path: Path = BDC_HOLDINGS_FILE) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path, dtype=str)
    except Exception as exc:
        logger.warning("Position purity: could not load %s: %s", path, exc)
        return None


def _prepare_bdc_source(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    prepared = df.copy()
    needed = [
        "cik", "report_date", "period", "accession_number",
        "investment_identifier", "dimensions_raw", "fair_value", "cost",
        "principal_amount", "shares_held",
    ]
    for col in needed:
        if col not in prepared.columns:
            prepared[col] = ""
    return prepared[needed]


def build_position_purity_diagnostics(
    holdings_df: pd.DataFrame,
    bdc_source_df: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build row-level diagnostics and CIK-quarter metrics.

    Duplicate candidates require the same normalized position identity and the
    same numeric facts across multiple BDC dimension paths. Comparative-period
    rows are emitted separately and are excluded from duplicate grouping by the
    ``period`` key.
    """
    if holdings_df.empty:
        return _empty_diagnostics(), _empty_metrics()

    holdings = _prepare_holdings(holdings_df)
    source = _prepare_bdc_source(
        bdc_source_df if bdc_source_df is not None else _load_bdc_source()
    )

    con = duckdb.connect()
    con.register("holdings", holdings)
    if source is not None:
        con.register("bdc_source", source)
        period_join = """
            LEFT JOIN (
                SELECT
                    right('0000000000' || regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10) AS src_cik,
                    report_date AS src_report_date,
                    accession_number AS src_accession_number,
                    investment_identifier,
                    dimensions_raw,
                    fair_value,
                    cost,
                    principal_amount,
                    shares_held,
                    MIN(period) AS source_period
                FROM bdc_source
                GROUP BY
                    regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'),
                    report_date, accession_number, investment_identifier,
                    dimensions_raw, fair_value, cost, principal_amount,
                    shares_held
            ) s
              ON right('0000000000' || regexp_replace(CAST(h.cik AS VARCHAR), '[^0-9]', '', 'g'), 10) = s.src_cik
             AND COALESCE(CAST(h.report_date AS VARCHAR), '') = COALESCE(CAST(s.src_report_date AS VARCHAR), '')
             AND COALESCE(CAST(h.accession_number AS VARCHAR), '') = COALESCE(CAST(s.src_accession_number AS VARCHAR), '')
             AND COALESCE(CAST(h.bdc_investment_identifier AS VARCHAR), '') = COALESCE(CAST(s.investment_identifier AS VARCHAR), '')
             AND COALESCE(CAST(h.bdc_dimensions_raw AS VARCHAR), '') = COALESCE(CAST(s.dimensions_raw AS VARCHAR), '')
             AND COALESCE(CAST(h.fair_value AS VARCHAR), '') = COALESCE(CAST(s.fair_value AS VARCHAR), '')
             AND COALESCE(CAST(h.cost AS VARCHAR), '') = COALESCE(CAST(s.cost AS VARCHAR), '')
             AND COALESCE(CAST(h.principal_amount AS VARCHAR), '') = COALESCE(CAST(s.principal_amount AS VARCHAR), '')
             AND COALESCE(CAST(h.shares_held AS VARCHAR), '') = COALESCE(CAST(s.shares_held AS VARCHAR), '')
        """
        period_expr = "COALESCE(NULLIF(CAST(h.period AS VARCHAR), ''), s.source_period, '')"
    else:
        period_join = ""
        period_expr = "COALESCE(CAST(h.period AS VARCHAR), '')"

    agg_expr = _sql_is_bdc_aggregate()
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE enriched AS
        WITH base AS (
            SELECT
                h.*,
                {period_expr} AS effective_period,
                COALESCE(
                    NULLIF(TRIM(CAST(h.bdc_investment_identifier AS VARCHAR)), ''),
                    NULLIF(TRIM(CAST(h.issuer_name AS VARCHAR)), ''),
                    ''
                ) AS _raw_id,
                lower(COALESCE(
                    NULLIF(TRIM(CAST(h.bdc_investment_identifier AS VARCHAR)), ''),
                    NULLIF(TRIM(CAST(h.issuer_name AS VARCHAR)), ''),
                    ''
                )) AS _lower_id
            FROM holdings h
            {period_join}
        )
        SELECT
            *,
            regexp_replace(lower(trim(CAST(issuer_name AS VARCHAR))), '[^a-z0-9]+', ' ', 'g') AS norm_issuer,
            regexp_replace(lower(trim(CAST(instrument_description AS VARCHAR))), '[^a-z0-9]+', ' ', 'g') AS norm_instrument,
            regexp_replace(lower(trim(CAST(cusip AS VARCHAR))), '[^a-z0-9]+', '', 'g') AS norm_cusip,
            regexp_replace(lower(trim(CAST(isin AS VARCHAR))), '[^a-z0-9]+', '', 'g') AS norm_isin,
            TRY_CAST(fair_value AS DOUBLE) AS fv_num,
            TRY_CAST(cost AS DOUBLE) AS cost_num,
            TRY_CAST(principal_amount AS DOUBLE) AS principal_num,
            TRY_CAST(shares_held AS DOUBLE) AS shares_num,
            ({agg_expr}) AS is_subtotal_candidate,
            (
                lower(COALESCE(CAST(source AS VARCHAR), '')) = 'bdc'
                AND TRY_CAST(effective_period AS DATE) IS NOT NULL
                AND TRY_CAST(report_date AS DATE) IS NOT NULL
                AND TRY_CAST(effective_period AS DATE) < TRY_CAST(report_date AS DATE)
            ) AS is_comparative_period
        FROM base
    """)

    diagnostics_sql = """
        WITH duplicate_groups AS (
            SELECT
                cik, report_date, accession_number, effective_period,
                COALESCE(NULLIF(norm_cusip, ''), NULLIF(norm_isin, ''),
                    norm_issuer || '|' || norm_instrument) AS norm_identity,
                ROUND(fv_num, 2) AS fv_key,
                ROUND(cost_num, 2) AS cost_key,
                ROUND(principal_num, 2) AS principal_key,
                ROUND(shares_num, 6) AS shares_key,
                COUNT(*) AS group_rows,
                COUNT(DISTINCT COALESCE(CAST(bdc_dimensions_raw AS VARCHAR), '')) AS dimension_path_count,
                MIN(CAST(_row_key AS VARCHAR)) AS duplicate_group_id
            FROM enriched
            WHERE lower(COALESCE(CAST(source AS VARCHAR), '')) = 'bdc'
              AND NOT is_comparative_period
              AND COALESCE(CAST(bdc_dimensions_raw AS VARCHAR), '') != ''
              AND COALESCE(NULLIF(norm_cusip, ''), NULLIF(norm_isin, ''),
                    norm_issuer || '|' || norm_instrument) != '|'
              AND fv_num IS NOT NULL
            GROUP BY
                cik, report_date, accession_number, effective_period,
                COALESCE(NULLIF(norm_cusip, ''), NULLIF(norm_isin, ''),
                    norm_issuer || '|' || norm_instrument),
                ROUND(fv_num, 2), ROUND(cost_num, 2),
                ROUND(principal_num, 2), ROUND(shares_num, 6)
            HAVING COUNT(*) > 1
               AND COUNT(DISTINCT COALESCE(CAST(bdc_dimensions_raw AS VARCHAR), '')) > 1
        ),
        duplicate_rows AS (
            SELECT
                'duplicate_dimension_candidate' AS issue_family,
                'same_identity_same_numeric_facts_multiple_dimension_paths' AS issue_type,
                e.source, e.cik, e.entity_name, e.report_date,
                e.effective_period AS period, e.accession_number,
                CAST(e._row_key AS VARCHAR) AS row_key,
                e.issuer_name, e.instrument_description,
                e.bdc_investment_identifier, e.bdc_dimensions_raw,
                e.fair_value, e.cost, e.principal_amount, e.shares_held,
                d.duplicate_group_id,
                d.dimension_path_count,
                'same normalized position identity and numeric facts across multiple bdc_dimensions_raw values' AS evidence,
                'REVIEW' AS recommended_action
            FROM enriched e
            JOIN duplicate_groups d
              ON e.cik = d.cik
             AND e.report_date = d.report_date
             AND e.accession_number = d.accession_number
             AND e.effective_period = d.effective_period
             AND COALESCE(NULLIF(e.norm_cusip, ''), NULLIF(e.norm_isin, ''),
                    e.norm_issuer || '|' || e.norm_instrument) = d.norm_identity
             AND ROUND(e.fv_num, 2) IS NOT DISTINCT FROM d.fv_key
             AND ROUND(e.cost_num, 2) IS NOT DISTINCT FROM d.cost_key
             AND ROUND(e.principal_num, 2) IS NOT DISTINCT FROM d.principal_key
             AND ROUND(e.shares_num, 6) IS NOT DISTINCT FROM d.shares_key
        ),
        subtotal_rows AS (
            SELECT
                'subtotal_candidate' AS issue_family,
                'aggregate_identifier_pattern' AS issue_type,
                source, cik, entity_name, report_date,
                effective_period AS period, accession_number,
                CAST(_row_key AS VARCHAR) AS row_key,
                issuer_name, instrument_description,
                bdc_investment_identifier, bdc_dimensions_raw,
                fair_value, cost, principal_amount, shares_held,
                '' AS duplicate_group_id,
                NULL AS dimension_path_count,
                'identifier matched BDC aggregate/subtotal diagnostic logic' AS evidence,
                'REVIEW' AS recommended_action
            FROM enriched
            WHERE lower(COALESCE(CAST(source AS VARCHAR), '')) = 'bdc'
              AND is_subtotal_candidate
        ),
        comparative_rows AS (
            SELECT
                'comparative_period' AS issue_family,
                'period_before_report_date' AS issue_type,
                source, cik, entity_name, report_date,
                effective_period AS period, accession_number,
                CAST(_row_key AS VARCHAR) AS row_key,
                issuer_name, instrument_description,
                bdc_investment_identifier, bdc_dimensions_raw,
                fair_value, cost, principal_amount, shares_held,
                '' AS duplicate_group_id,
                NULL AS dimension_path_count,
                'source period is earlier than report_date; retained as comparative-period fact' AS evidence,
                'TRACK_ONLY' AS recommended_action
            FROM enriched
            WHERE is_comparative_period
        )
        SELECT * FROM subtotal_rows
        UNION ALL
        SELECT * FROM duplicate_rows
        UNION ALL
        SELECT * FROM comparative_rows
        ORDER BY cik, report_date, issue_family, row_key
    """
    diagnostics = con.execute(diagnostics_sql).fetchdf()
    if diagnostics.empty:
        diagnostics = _empty_diagnostics()
    else:
        diagnostics = diagnostics[DIAGNOSTIC_COLUMNS]

    con.register("diagnostics", diagnostics)
    metrics = con.execute("""
        WITH base AS (
            SELECT
                source, cik, entity_name, report_date,
                CASE WHEN TRY_CAST(report_date AS DATE) IS NOT NULL THEN
                    CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                    || 'q'
                    || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                ELSE '' END AS quarter,
                COUNT(*) AS row_count
            FROM enriched
            GROUP BY source, cik, entity_name, report_date, quarter
        ),
        issue_summary AS (
            SELECT
                source, cik, report_date,
                SUM(CASE WHEN issue_family = 'subtotal_candidate' THEN 1 ELSE 0 END) AS subtotal_candidate_rows,
                SUM(CASE WHEN issue_family = 'subtotal_candidate' THEN COALESCE(TRY_CAST(fair_value AS DOUBLE), 0) ELSE 0 END) AS subtotal_candidate_fv,
                SUM(CASE WHEN issue_family = 'duplicate_dimension_candidate' THEN 1 ELSE 0 END) AS duplicate_dimension_candidate_rows,
                SUM(CASE WHEN issue_family = 'duplicate_dimension_candidate' THEN COALESCE(TRY_CAST(fair_value AS DOUBLE), 0) ELSE 0 END) AS duplicate_dimension_candidate_fv,
                SUM(CASE WHEN issue_family = 'comparative_period' THEN 1 ELSE 0 END) AS comparative_period_rows,
                SUM(CASE WHEN issue_family = 'comparative_period' THEN COALESCE(TRY_CAST(fair_value AS DOUBLE), 0) ELSE 0 END) AS comparative_period_fv,
                COUNT(*) AS issue_rows,
                SUM(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0)) AS affected_fair_value
            FROM diagnostics
            GROUP BY source, cik, report_date
        )
        SELECT
            b.source, b.cik, b.entity_name, b.report_date, b.quarter,
            b.row_count,
            COALESCE(i.subtotal_candidate_rows, 0) AS subtotal_candidate_rows,
            COALESCE(i.subtotal_candidate_fv, 0) AS subtotal_candidate_fv,
            COALESCE(i.duplicate_dimension_candidate_rows, 0) AS duplicate_dimension_candidate_rows,
            COALESCE(i.duplicate_dimension_candidate_fv, 0) AS duplicate_dimension_candidate_fv,
            COALESCE(i.comparative_period_rows, 0) AS comparative_period_rows,
            COALESCE(i.comparative_period_fv, 0) AS comparative_period_fv,
            COALESCE(i.issue_rows, 0) AS issue_rows,
            COALESCE(i.affected_fair_value, 0) AS affected_fair_value
        FROM base b
        LEFT JOIN issue_summary i
          ON b.source = i.source
         AND b.cik = i.cik
         AND b.report_date = i.report_date
        ORDER BY b.source, b.cik, b.report_date
    """).fetchdf()
    con.close()

    if metrics.empty:
        metrics = _empty_metrics()
    return diagnostics[DIAGNOSTIC_COLUMNS], metrics[METRIC_COLUMNS]
