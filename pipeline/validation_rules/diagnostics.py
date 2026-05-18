"""Report-only diagnostic calibration harness for validation-rule candidates.

This module reads cached output CSV artifacts, computes diagnostic candidates
with DuckDB, and writes review artifacts under
data/output/diagnostic_calibration. It intentionally does not import or mutate
RULE_REGISTRY.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import duckdb
import jsonschema
import pandas as pd

from pipeline import config

SCHEMA_VERSION = "1.0"
CALIBRATION_DIRNAME = "diagnostic_calibration"
ALLOWED_REVIEW_ACTIONS = {
    "drop",
    "keep_report_only",
    "add_as_unpromoted_rule",
    "refine_and_retest",
    "promote_to_warn",
}

FINDING_COLUMNS = [
    "calibration_run_id",
    "run_timestamp",
    "calibration_id",
    "candidate_id",
    "threshold_value",
    "cik",
    "quarter",
    "prior_quarter",
    "granularity_key",
    "issuer_name",
    "position_id",
    "metric_value",
    "affected_fair_value",
    "detail",
    "evidence_hint",
    "source_files",
]

SUMMARY_COLUMNS = [
    "calibration_run_id",
    "run_timestamp",
    "candidate_id",
    "quarters_tested",
    "population_count",
    "hit_count",
    "hit_rate",
    "affected_fair_value",
    "top_ciks",
    "top_quarters",
    "top_examples",
    "false_positive_notes",
    "recommended_action",
]

THRESHOLD_GRID_COLUMNS = [
    "calibration_run_id",
    "run_timestamp",
    "calibration_id",
    "candidate_id",
    "candidate_version",
    "threshold_value",
    "quarters_tested",
    "population_count",
    "hit_count",
    "hit_rate",
    "affected_fair_value",
    "top_ciks",
    "top_quarters",
    "top_examples",
    "input_hashes",
    "git_head",
    "git_status_summary",
]

MANIFEST_COLUMNS = [
    "calibration_id",
    "candidate_id",
    "threshold_value",
    "bundle_path",
    "bundle_sha256",
    "top_n",
    "finding_count",
    "created_at",
]

REVIEW_SUMMARY_COLUMNS = [
    "calibration_id",
    "candidate_id",
    "verdict",
    "confidence",
    "recommended_action",
    "review_count",
    "promote_to_warn_eligible",
]

TABLE_PATHS = {
    "holdings": config.UNIFIED_HOLDINGS_FILE,
    "position_matches": config.POSITION_MATCHES_FILE,
    "position_returns": config.POSITION_RETURNS_FILE,
    "index_returns": config.INDEX_RETURNS_FILE,
    "validation_rules_detail": config.VALIDATION_RULES_DETAIL_FILE,
}

EXPECTED_COLUMNS = {
    "holdings": [
        "cik",
        "quarter",
        "report_date",
        "issuer_name",
        "position_id",
        "instrument_description",
        "source",
        "fair_value",
        "index_classification",
    ],
    "position_matches": [
        "cik",
        "source",
        "begin_quarter",
        "end_quarter",
        "begin_issuer_name",
        "end_issuer_name",
        "begin_fair_value",
        "end_fair_value",
        "match_method",
        "position_id",
    ],
    "position_returns": [
        "cik",
        "source",
        "begin_quarter",
        "end_quarter",
        "issuer_name",
        "index_classification",
        "begin_fair_value",
        "end_fair_value",
        "position_id",
    ],
    "index_returns": [
        "index_classification",
        "quarter",
        "constituent_count",
        "total_begin_fv",
        "total_end_fv",
    ],
    "validation_rules_detail": [
        "finding_key",
        "rule_id",
        "category",
        "severity",
        "granularity_key",
        "cik",
        "quarter",
        "report_date",
        "issuer_name",
        "position_id",
        "affected_fair_value",
        "detail",
        "evidence_hint",
        "source_file",
    ],
}


class DiagnosticCalibrationError(RuntimeError):
    """Raised when calibration inputs or review artifacts are invalid."""


@dataclass(frozen=True)
class DiagnosticCandidate:
    candidate_id: str
    title: str
    version: str
    required_tables: tuple[str, ...]
    thresholds: tuple[float, ...]
    sql: str
    rationale: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(config.PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _quote(path: Path) -> str:
    return str(path).replace("'", "''")


def _threshold_label(value: float) -> str:
    text = f"{value:g}".replace(".", "p").replace("-", "m")
    return text


def _calibration_id(candidate: DiagnosticCandidate, threshold: float, input_hashes: dict[str, str]) -> str:
    identity = json.dumps(
        {
            "candidate_id": candidate.candidate_id,
            "version": candidate.version,
            "threshold": threshold,
            "input_hashes": input_hashes,
        },
        sort_keys=True,
    )
    return f"{candidate.candidate_id}_{_threshold_label(threshold)}_{short_hash(identity)}"


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=config.PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _git_status_summary() -> str:
    try:
        lines = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=config.PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).splitlines()
    except Exception:
        return ""
    if not lines:
        return "clean"
    counts: dict[str, int] = {}
    for line in lines:
        status = line[:2].strip() or "??"
        counts[status] = counts.get(status, 0) + 1
    return ";".join(f"{k}:{counts[k]}" for k in sorted(counts))


def _base_metric_select(metric_cte: str, detail: str, evidence_hint: str, source_files: str) -> str:
    return f"""
    WITH metric AS (
      WITH {metric_cte}
    )
    SELECT
      CAST(cik AS VARCHAR) AS cik,
      CAST(quarter AS VARCHAR) AS quarter,
      CAST(prior_quarter AS VARCHAR) AS prior_quarter,
      CAST(granularity_key AS VARCHAR) AS granularity_key,
      CAST(issuer_name AS VARCHAR) AS issuer_name,
      CAST(position_id AS VARCHAR) AS position_id,
      CAST(metric_value AS DOUBLE) AS metric_value,
      CAST(affected_fair_value AS DOUBLE) AS affected_fair_value,
      CAST('{detail}' AS VARCHAR) AS detail,
      CAST('{evidence_hint}' AS VARCHAR) AS evidence_hint,
      CAST('{source_files}' AS VARCHAR) AS source_files
    FROM metric
    """


def _candidates() -> dict[str, DiagnosticCandidate]:
    q_expr = "COALESCE(NULLIF(quarter, ''), report_date)"
    h_q_expr = "COALESCE(NULLIF(h.quarter, ''), h.report_date)"
    dist01 = _base_metric_select(
        f"""
        q AS (
          SELECT cik, {q_expr} AS quarter,
                 MAX(TRY_CAST(report_date AS DATE)) AS period_date,
                 median(TRY_CAST(fair_value AS DOUBLE)) AS median_fv,
                 SUM(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0)) AS total_fv,
                 COUNT(*) AS n,
                 COUNT(DISTINCT lower(trim(COALESCE(source, '')))) AS source_count,
                 MIN(lower(trim(COALESCE(source, '')))) AS source_key
          FROM holdings
          WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
          GROUP BY cik, {q_expr}
        ), lagged AS (
          SELECT *, LAG(quarter) OVER w AS prior_quarter,
                    LAG(period_date) OVER w AS prior_period_date,
                    LAG(median_fv) OVER w AS prior_median_fv,
                    LAG(total_fv) OVER w AS prior_total_fv,
                    LAG(n) OVER w AS prior_n,
                    LAG(source_count) OVER w AS prior_source_count,
                    LAG(source_key) OVER w AS prior_source_key
          FROM q
          WINDOW w AS (PARTITION BY cik ORDER BY period_date, quarter)
        ), ratios AS (
          SELECT *,
                 median_fv / NULLIF(prior_median_fv, 0) AS median_ratio,
                 total_fv / NULLIF(prior_total_fv, 0) AS total_fv_ratio
          FROM lagged
        )
        SELECT cik, quarter, prior_quarter, cik || '|' || quarter AS granularity_key,
               NULL AS issuer_name, NULL AS position_id,
               LEAST(ABS(LOG10(median_ratio)), ABS(LOG10(total_fv_ratio))) AS metric_value,
               total_fv AS affected_fair_value
        FROM ratios
        WHERE prior_median_fv IS NOT NULL
          AND period_date IS NOT NULL
          AND prior_period_date IS NOT NULL
          AND date_diff('day', prior_period_date, period_date) BETWEEN 60 AND 140
          AND source_count = 1 AND prior_source_count = 1 AND source_key = prior_source_key
          AND n >= 10 AND prior_n >= 10
          AND median_fv > 0 AND prior_median_fv > 0
          AND total_fv > 0 AND prior_total_fv > 0
          AND ((median_ratio >= 1 AND total_fv_ratio >= 1) OR (median_ratio <= 1 AND total_fv_ratio <= 1))
        """,
        "Scale-consistent QoQ fair value drift per CIK",
        "Check same-source adjacent CIK-quarters where median and total fair value moved in the same scale direction.",
        "private_markets_holdings.csv",
    )
    dist02 = _base_metric_select(
        f"""
        q AS (
          SELECT cik, {q_expr} AS quarter,
                 MAX(TRY_CAST(report_date AS DATE)) AS period_date,
                 COUNT(DISTINCT lower(trim(issuer_name))) AS issuer_count,
                 COUNT(*) AS row_count,
                 SUM(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0)) AS total_fv,
                 COUNT(DISTINCT lower(trim(COALESCE(source, '')))) AS source_count,
                 MIN(lower(trim(COALESCE(source, '')))) AS source_key
          FROM holdings
          WHERE COALESCE(issuer_name, '') <> ''
          GROUP BY cik, {q_expr}
        ), lagged AS (
          SELECT *, LAG(quarter) OVER w AS prior_quarter,
                    LAG(period_date) OVER w AS prior_period_date,
                    LAG(issuer_count) OVER w AS prior_issuer_count,
                    LAG(row_count) OVER w AS prior_row_count,
                    LAG(total_fv) OVER w AS prior_total_fv,
                    LAG(source_count) OVER w AS prior_source_count,
                    LAG(source_key) OVER w AS prior_source_key
          FROM q
          WINDOW w AS (PARTITION BY cik ORDER BY period_date, quarter)
        ), metrics AS (
          SELECT *,
                 ABS(issuer_count::DOUBLE / NULLIF(prior_issuer_count, 0) - 1) AS issuer_metric,
                 ABS(row_count::DOUBLE / NULLIF(prior_row_count, 0) - 1) AS row_metric,
                 ABS(total_fv / NULLIF(prior_total_fv, 0) - 1) AS fv_metric
          FROM lagged
        )
        SELECT cik, quarter, prior_quarter, cik || '|' || quarter AS granularity_key,
               NULL AS issuer_name, NULL AS position_id,
               issuer_metric AS metric_value,
               total_fv AS affected_fair_value
        FROM metrics
        WHERE prior_issuer_count IS NOT NULL
          AND period_date IS NOT NULL
          AND prior_period_date IS NOT NULL
          AND date_diff('day', prior_period_date, period_date) BETWEEN 60 AND 140
          AND source_count = 1 AND prior_source_count = 1 AND source_key = prior_source_key
          AND issuer_count >= 10 AND prior_issuer_count >= 10
          AND row_metric < 0.25
          AND fv_metric < 0.50
        """,
        "Residual issuer-count shock per CIK-quarter",
        "Inspect issuer-count movement after filtering out broad row-count or fair-value coverage shocks.",
        "private_markets_holdings.csv",
    )
    dist04 = _base_metric_select(
        f"""
        ranked AS (
          SELECT cik, {q_expr} AS quarter, issuer_name, position_id,
                 COALESCE(TRY_CAST(fair_value AS DOUBLE), 0) AS fv,
                 ROW_NUMBER() OVER (
                   PARTITION BY cik, {q_expr}
                   ORDER BY COALESCE(TRY_CAST(fair_value AS DOUBLE), 0) DESC, issuer_name, position_id
                 ) AS rn
          FROM holdings
        ), q AS (
          SELECT cik, quarter,
                 SUM(CASE WHEN rn <= 10 THEN fv ELSE 0 END) / NULLIF(SUM(fv), 0) AS top10_share,
                 SUM(fv) AS total_fv,
                 MAX(CASE WHEN rn = 1 THEN issuer_name ELSE NULL END) AS issuer_name,
                 MAX(CASE WHEN rn = 1 THEN position_id ELSE NULL END) AS position_id
          FROM ranked
          GROUP BY cik, quarter
          HAVING SUM(fv) > 0
        ), lagged AS (
          SELECT *, LAG(quarter) OVER w AS prior_quarter,
                    LAG(top10_share) OVER w AS prior_top10_share
          FROM q
          WINDOW w AS (PARTITION BY cik ORDER BY quarter)
        )
        SELECT cik, quarter, prior_quarter, cik || '|' || quarter AS granularity_key,
               issuer_name, position_id,
               ABS(top10_share - prior_top10_share) AS metric_value,
               total_fv AS affected_fair_value
        FROM lagged
        WHERE prior_top10_share IS NOT NULL
        """,
        "Top-10 concentration share shift",
        "Inspect top holdings for subtotal leakage, missing long tail, or true portfolio concentration shift.",
        "private_markets_holdings.csv",
    )
    dist05 = _base_metric_select(
        f"""
        q_issuer AS (
          SELECT cik, {q_expr} AS quarter, lower(trim(issuer_name)) AS issuer_name,
                 MAX(TRY_CAST(report_date AS DATE)) AS period_date,
                 MIN(issuer_name) AS display_issuer,
                 MIN(position_id) AS position_id,
                 SUM(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0)) AS fv
          FROM holdings
          WHERE COALESCE(issuer_name, '') <> ''
          GROUP BY cik, {q_expr}, lower(trim(issuer_name))
        ), q_position AS (
          SELECT cik, {q_expr} AS quarter, lower(trim(position_id)) AS position_id,
                 SUM(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0)) AS fv
          FROM holdings
          WHERE COALESCE(position_id, '') <> ''
          GROUP BY cik, {q_expr}, lower(trim(position_id))
        ), quarters AS (
          SELECT cik, quarter, period_date, issuer_count,
                 LAG(quarter) OVER w AS prior_quarter,
                 LAG(period_date) OVER w AS prior_period_date,
                 LAG(issuer_count) OVER w AS prior_issuer_count
          FROM (
            SELECT cik, quarter, MAX(period_date) AS period_date, COUNT(*) AS issuer_count
            FROM q_issuer
            GROUP BY cik, quarter
          )
          WINDOW w AS (PARTITION BY cik ORDER BY period_date, quarter)
        ), issuer_marked AS (
          SELECT c.*, q.prior_quarter,
                 q.prior_period_date,
                 q.prior_issuer_count,
                 CASE WHEN p.issuer_name IS NULL THEN 1 ELSE 0 END AS is_new
          FROM q_issuer c
          JOIN quarters q ON c.cik = q.cik AND c.quarter = q.quarter
          LEFT JOIN q_issuer p ON p.cik = c.cik AND p.quarter = q.prior_quarter AND p.issuer_name = c.issuer_name
          WHERE q.prior_quarter IS NOT NULL
        ), issuer_agg AS (
          SELECT cik, quarter, prior_quarter,
                 MAX(period_date) AS period_date,
                 MAX(prior_period_date) AS prior_period_date,
                 MAX(prior_issuer_count) AS prior_issuer_count,
                 COUNT(*) AS issuer_count,
                 SUM(is_new)::DOUBLE / NULLIF(COUNT(*), 0) AS issuer_new_ratio,
                 SUM(CASE WHEN is_new = 1 THEN fv ELSE 0 END) / NULLIF(SUM(fv), 0) AS issuer_new_fv_share,
                 SUM(CASE WHEN is_new = 1 THEN fv ELSE 0 END) AS new_issuer_fv,
                 arg_max(display_issuer, is_new * fv) AS issuer_name,
                 arg_max(position_id, is_new * fv) AS position_id
          FROM issuer_marked
          GROUP BY cik, quarter, prior_quarter
        ), position_marked AS (
          SELECT c.cik, c.quarter, q.prior_quarter, c.fv,
                 CASE WHEN p.position_id IS NULL THEN 1 ELSE 0 END AS is_new
          FROM q_position c
          JOIN quarters q ON c.cik = q.cik AND c.quarter = q.quarter
          LEFT JOIN q_position p ON p.cik = c.cik AND p.quarter = q.prior_quarter AND p.position_id = c.position_id
          WHERE q.prior_quarter IS NOT NULL
        ), position_agg AS (
          SELECT cik, quarter, prior_quarter,
                 SUM(is_new)::DOUBLE / NULLIF(COUNT(*), 0) AS position_new_ratio,
                 SUM(CASE WHEN is_new = 1 THEN fv ELSE 0 END) / NULLIF(SUM(fv), 0) AS position_new_fv_share
          FROM position_marked
          GROUP BY cik, quarter, prior_quarter
        )
        SELECT cik, quarter, prior_quarter, cik || '|' || quarter AS granularity_key,
               issuer_name, position_id,
               LEAST(issuer_new_ratio, issuer_new_fv_share) AS metric_value,
               new_issuer_fv AS affected_fair_value
        FROM issuer_agg
        JOIN position_agg USING (cik, quarter, prior_quarter)
        WHERE period_date IS NOT NULL
          AND prior_period_date IS NOT NULL
          AND date_diff('day', prior_period_date, period_date) BETWEEN 60 AND 140
          AND issuer_count >= 10
          AND prior_issuer_count >= 10
          AND position_new_ratio < 0.25
          AND position_new_fv_share < 0.35
        """,
        "Issuer-string churn against stable positions",
        "Review CIK-quarters where issuer names churn while position identifiers remain comparatively stable.",
        "private_markets_holdings.csv",
    )
    mono03 = _base_metric_select(
        f"""
        quarters AS (
          SELECT cik, {q_expr} AS quarter,
                 DENSE_RANK() OVER (PARTITION BY cik ORDER BY {q_expr}) AS q_idx
          FROM holdings
          GROUP BY cik, {q_expr}
        ), obs AS (
          SELECT h.cik, {h_q_expr} AS quarter, q.q_idx, h.position_id,
                 MAX(h.issuer_name) AS issuer_name,
                 SUM(COALESCE(TRY_CAST(h.fair_value AS DOUBLE), 0)) AS fv
          FROM holdings h
          JOIN quarters q ON h.cik = q.cik AND {h_q_expr} = q.quarter
          WHERE COALESCE(h.position_id, '') <> ''
          GROUP BY h.cik, {h_q_expr}, q.q_idx, h.position_id
        ), lagged AS (
          SELECT *, LAG(quarter) OVER w AS prior_quarter,
                    LAG(q_idx) OVER w AS prior_q_idx,
                    LAG(fv) OVER w AS prior_fv
          FROM obs
          WINDOW w AS (PARTITION BY cik, position_id ORDER BY q_idx)
        )
        SELECT cik, quarter, prior_quarter, cik || '|' || position_id || '|' || quarter AS granularity_key,
               issuer_name, position_id,
               (q_idx - prior_q_idx - 1)::DOUBLE AS metric_value,
               fv AS affected_fair_value
        FROM lagged
        WHERE prior_q_idx IS NOT NULL AND q_idx - prior_q_idx > 1
          AND fv > 0 AND prior_fv > 0
          AND ABS(fv / NULLIF(prior_fv, 0) - 1) <= 0.50
        """,
        "Position disappears then reappears after a gap",
        "Inspect matching continuity and source coverage for the missing intervening quarter(s).",
        "private_markets_holdings.csv",
    )
    mono05 = _base_metric_select(
        f"""
        obs AS (
          SELECT cik, {q_expr} AS quarter, position_id,
                 MAX(TRY_CAST(report_date AS DATE)) AS period_date,
                 COUNT(*) AS row_count,
                 COUNT(DISTINCT lower(trim(COALESCE(source, '')))) AS source_count,
                 MIN(lower(trim(COALESCE(source, '')))) AS source_key,
                 COUNT(DISTINCT lower(trim(COALESCE(issuer_name, '')))) AS issuer_count,
                 MIN(lower(trim(COALESCE(issuer_name, '')))) AS issuer_key,
                 MAX(issuer_name) AS issuer_name,
                 COUNT(DISTINCT upper(trim(COALESCE(index_classification, '')))) AS class_count,
                 MAX(upper(trim(COALESCE(index_classification, '')))) AS index_classification,
                 COUNT(DISTINCT regexp_replace(lower(trim(COALESCE(instrument_description, ''))), '\\s+', ' ', 'g')) AS instrument_count,
                 MIN(regexp_replace(lower(trim(COALESCE(instrument_description, ''))), '\\s+', ' ', 'g')) AS instrument_key,
                 SUM(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0)) AS fv
          FROM holdings
          WHERE COALESCE(position_id, '') <> ''
            AND COALESCE(index_classification, '') <> ''
          GROUP BY cik, {q_expr}, position_id
        ), lagged AS (
          SELECT *, LAG(quarter) OVER w AS prior_quarter,
                    LAG(period_date) OVER w AS prior_period_date,
                    LAG(row_count) OVER w AS prior_row_count,
                    LAG(source_count) OVER w AS prior_source_count,
                    LAG(source_key) OVER w AS prior_source_key,
                    LAG(issuer_count) OVER w AS prior_issuer_count,
                    LAG(issuer_key) OVER w AS prior_issuer_key,
                    LAG(class_count) OVER w AS prior_class_count,
                    LAG(index_classification) OVER w AS prior_classification,
                    LAG(instrument_count) OVER w AS prior_instrument_count,
                    LAG(instrument_key) OVER w AS prior_instrument_key,
                    LAG(fv) OVER w AS prior_fv
          FROM obs
          WINDOW w AS (PARTITION BY cik, position_id ORDER BY period_date, quarter)
        )
        SELECT cik, quarter, prior_quarter, cik || '|' || position_id || '|' || quarter AS granularity_key,
               issuer_name, position_id, 1.0 AS metric_value, fv AS affected_fair_value
        FROM lagged
        WHERE prior_classification IS NOT NULL
          AND period_date IS NOT NULL
          AND prior_period_date IS NOT NULL
          AND date_diff('day', prior_period_date, period_date) BETWEEN 60 AND 140
          AND row_count = 1 AND prior_row_count = 1
          AND source_count = 1 AND prior_source_count = 1 AND source_key = prior_source_key
          AND issuer_count = 1 AND prior_issuer_count = 1 AND issuer_key = prior_issuer_key
          AND class_count = 1 AND prior_class_count = 1
          AND instrument_count = 1 AND prior_instrument_count = 1 AND instrument_key = prior_instrument_key
          AND index_classification NOT IN ('UNCLASSIFIED', 'CASH')
          AND prior_classification NOT IN ('UNCLASSIFIED', 'CASH')
          AND prior_fv > 0
          AND ABS(fv / NULLIF(prior_fv, 0) - 1) < 0.50
          AND index_classification <> prior_classification
        """,
        "Stable-identity private-class flip",
        "Confirm same-source, same-issuer, same-instrument private positions that changed index classification across adjacent periods.",
        "private_markets_holdings.csv",
    )
    candidates = [
        DiagnosticCandidate("DIST01", "Scale-consistent QoQ fair value drift per CIK", "2026-05-18.2", ("holdings",), (1.0, 2.0, 3.0), dist01, "May reveal same-source scale breaks after composition-only moves are filtered."),
        DiagnosticCandidate("DIST02", "Residual issuer-count shock per CIK-quarter", "2026-05-18.2", ("holdings",), (0.5, 1.0, 2.0), dist02, "Issuer-count movement after stable row-count and fair-value filters."),
        DiagnosticCandidate("DIST04", "Top-10 concentration shift", "2026-05-18.1", ("holdings",), (0.15, 0.25, 0.50), dist04, "Can surface subtotal leaks or missing long-tail positions."),
        DiagnosticCandidate("DIST05", "Issuer-string churn against stable positions", "2026-05-18.2", ("holdings",), (0.60, 0.80, 0.95), dist05, "Can surface issuer-string churn distinct from true new-position turnover."),
        DiagnosticCandidate("MONO03", "Disappears then reappears after a gap", "2026-05-18.1", ("holdings",), (1.0, 2.0, 4.0), mono03, "Can reveal position matching chain breaks."),
        DiagnosticCandidate("MONO05", "Stable-identity private-class flip", "2026-05-18.2", ("holdings",), (1.0,), mono05, "Overlaps T04 but filtered to stable private-position identity."),
    ]
    return {candidate.candidate_id: candidate for candidate in candidates}


CANDIDATES = _candidates()


def output_root(output_dir: Path = config.OUTPUT_DIR) -> Path:
    return output_dir / CALIBRATION_DIRNAME


def _load_tables(
    con: duckdb.DuckDBPyConnection,
    candidates: Iterable[DiagnosticCandidate],
    table_paths: dict[str, str | Path] | None,
) -> tuple[dict[str, Path], dict[str, str]]:
    paths = {**TABLE_PATHS, **(table_paths or {})}
    needed = {table for candidate in candidates for table in candidate.required_tables}
    loaded: dict[str, Path] = {}
    missing: dict[str, str] = {}
    for table in sorted(needed):
        path = Path(paths[table])
        if not path.exists():
            missing[table] = f"missing file: {path}"
            continue
        raw = f"_{table}_raw"
        con.execute(
            f"""
            CREATE TEMP VIEW {raw} AS
            SELECT * FROM read_csv('{_quote(path)}', header=true, all_varchar=true, ignore_errors=true)
            """
        )
        cols = {row[1].lower(): row[1] for row in con.execute(f"PRAGMA table_info('{raw}')").fetchall()}
        selects = []
        for col in EXPECTED_COLUMNS[table]:
            if col.lower() in cols:
                selects.append(f'CAST("{cols[col.lower()]}" AS VARCHAR) AS {col}')
            else:
                selects.append(f"CAST(NULL AS VARCHAR) AS {col}")
        con.execute(f"CREATE TEMP VIEW {table} AS SELECT {', '.join(selects)} FROM {raw}")
        loaded[table] = path
    return loaded, missing


def _top_values(df: pd.DataFrame, column: str, n: int = 5) -> str:
    if df.empty or column not in df:
        return ""
    counts = df[column].fillna("").astype(str)
    counts = counts[counts != ""].value_counts().head(n)
    return ";".join(f"{idx}:{int(value)}" for idx, value in counts.items())


def _top_examples(df: pd.DataFrame, n: int = 5) -> str:
    if df.empty:
        return ""
    rows = df.sort_values(
        ["metric_value", "affected_fair_value", "granularity_key"],
        ascending=[False, False, True],
        kind="mergesort",
    ).head(n)
    values = []
    for row in rows.to_dict("records"):
        values.append(
            "|".join(
                str(row.get(k, "") or "")
                for k in ["calibration_id", "cik", "quarter", "issuer_name", "position_id"]
            )
        )
    return ";".join(values)


def _write_csv(path: Path, df: pd.DataFrame, columns: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        pd.DataFrame(columns=columns).to_csv(path, index=False)
    else:
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        df.loc[:, columns].to_csv(path, index=False)
    return path


def run_calibration(
    candidate_ids: Iterable[str] | None = None,
    output_dir: Path = config.OUTPUT_DIR,
    table_paths: dict[str, str | Path] | None = None,
    calibration_run_id: str | None = None,
) -> dict[str, Path]:
    selected_ids = [cid.upper() for cid in (candidate_ids or CANDIDATES)]
    unknown = sorted(set(selected_ids) - set(CANDIDATES))
    if unknown:
        raise DiagnosticCalibrationError(f"Unknown diagnostic candidate(s): {', '.join(unknown)}")
    selected = [CANDIDATES[cid] for cid in selected_ids]
    run_id = calibration_run_id or uuid4().hex[:12]
    ts = now_iso()
    git_head = _git_head()
    git_status = _git_status_summary()

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    loaded_paths, missing = _load_tables(con, selected, table_paths)
    input_hashes = {table: sha256_file(path) for table, path in sorted(loaded_paths.items())}

    finding_frames: list[pd.DataFrame] = []
    grid_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for candidate in selected:
        missing_for_candidate = [missing[t] for t in candidate.required_tables if t in missing]
        if missing_for_candidate:
            summary_rows.append({
                "calibration_run_id": run_id,
                "run_timestamp": ts,
                "candidate_id": candidate.candidate_id,
                "quarters_tested": 0,
                "population_count": 0,
                "hit_count": 0,
                "hit_rate": 0.0,
                "affected_fair_value": 0.0,
                "top_ciks": "",
                "top_quarters": "",
                "top_examples": "",
                "false_positive_notes": "; ".join(missing_for_candidate),
                "recommended_action": "needs_agent_review",
            })
            continue
        metrics = con.execute(candidate.sql).fetchdf()
        if metrics.empty:
            metrics = pd.DataFrame(columns=[
                "cik", "quarter", "prior_quarter", "granularity_key", "issuer_name",
                "position_id", "metric_value", "affected_fair_value", "detail",
                "evidence_hint", "source_files",
            ])
        metrics["metric_value"] = pd.to_numeric(metrics["metric_value"], errors="coerce")
        metrics["affected_fair_value"] = pd.to_numeric(metrics["affected_fair_value"], errors="coerce").fillna(0)
        quarters_tested = int(metrics["quarter"].nunique()) if "quarter" in metrics else 0
        population_count = int(len(metrics))
        candidate_hit_frames: list[pd.DataFrame] = []
        for threshold in candidate.thresholds:
            calibration_id = _calibration_id(candidate, threshold, input_hashes)
            hits = metrics[metrics["metric_value"] >= threshold].copy()
            hits = hits.sort_values(
                ["metric_value", "affected_fair_value", "granularity_key"],
                ascending=[False, False, True],
                kind="mergesort",
            ).reset_index(drop=True)
            hits["calibration_run_id"] = run_id
            hits["run_timestamp"] = ts
            hits["calibration_id"] = calibration_id
            hits["candidate_id"] = candidate.candidate_id
            hits["threshold_value"] = threshold
            if not hits.empty:
                finding_frames.append(hits.loc[:, FINDING_COLUMNS])
                candidate_hit_frames.append(hits)
            grid_rows.append({
                "calibration_run_id": run_id,
                "run_timestamp": ts,
                "calibration_id": calibration_id,
                "candidate_id": candidate.candidate_id,
                "candidate_version": candidate.version,
                "threshold_value": threshold,
                "quarters_tested": quarters_tested,
                "population_count": population_count,
                "hit_count": int(len(hits)),
                "hit_rate": float(len(hits) / population_count) if population_count else 0.0,
                "affected_fair_value": float(hits["affected_fair_value"].sum()) if not hits.empty else 0.0,
                "top_ciks": _top_values(hits, "cik"),
                "top_quarters": _top_values(hits, "quarter"),
                "top_examples": _top_examples(hits),
                "input_hashes": json.dumps(input_hashes, sort_keys=True),
                "git_head": git_head,
                "git_status_summary": git_status,
            })
        all_hits = pd.concat(candidate_hit_frames, ignore_index=True) if candidate_hit_frames else pd.DataFrame()
        unique_hits = (
            all_hits.sort_values(
                ["metric_value", "affected_fair_value", "granularity_key"],
                ascending=[False, False, True],
                kind="mergesort",
            ).drop_duplicates(["granularity_key"], keep="first")
            if not all_hits.empty else pd.DataFrame()
        )
        summary_rows.append({
            "calibration_run_id": run_id,
            "run_timestamp": ts,
            "candidate_id": candidate.candidate_id,
            "quarters_tested": quarters_tested,
            "population_count": population_count,
            "hit_count": int(len(unique_hits)),
            "hit_rate": float(len(unique_hits) / population_count) if population_count else 0.0,
            "affected_fair_value": float(unique_hits["affected_fair_value"].sum()) if not unique_hits.empty else 0.0,
            "top_ciks": _top_values(unique_hits, "cik"),
            "top_quarters": _top_values(unique_hits, "quarter"),
            "top_examples": _top_examples(unique_hits),
            "false_positive_notes": "Machine calibration only; agent review required before promotion.",
            "recommended_action": "needs_agent_review",
        })
    con.close()

    root = output_root(output_dir)
    findings_df = pd.concat(finding_frames, ignore_index=True) if finding_frames else pd.DataFrame(columns=FINDING_COLUMNS)
    summary_df = pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS)
    grid_df = pd.DataFrame(grid_rows, columns=THRESHOLD_GRID_COLUMNS)
    return {
        "findings": _write_csv(root / "candidate_findings.csv", findings_df, FINDING_COLUMNS),
        "summary": _write_csv(root / "candidate_summary.csv", summary_df, SUMMARY_COLUMNS),
        "threshold_grid": _write_csv(root / "candidate_threshold_grid.csv", grid_df, THRESHOLD_GRID_COLUMNS),
    }


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write_csv_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})
    return path


def _artifact(path: Path) -> dict[str, str]:
    return {
        "path": display_path(path),
        "sha256": sha256_file(path) if path.exists() else "",
        "status": "present" if path.exists() else "missing",
    }


def _matching_rows(path: Path, predicate, limit: int = 50) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if predicate(row):
                rows.append(row)
                if len(rows) >= limit:
                    break
    return rows


def _schema_path(name: str) -> Path:
    return config.PROJECT_ROOT / "schemas" / CALIBRATION_DIRNAME / name


def build_review_bundle(
    candidate_id: str,
    output_dir: Path = config.OUTPUT_DIR,
    top_n: int = 20,
    calibration_id: str | None = None,
) -> Path:
    root = output_root(output_dir)
    findings = _read_csv_rows(root / "candidate_findings.csv")
    grid = _read_csv_rows(root / "candidate_threshold_grid.csv")
    candidate_id = candidate_id.upper()
    if calibration_id:
        grid_rows = [r for r in grid if r.get("calibration_id") == calibration_id]
    else:
        grid_rows = [r for r in grid if r.get("candidate_id") == candidate_id]
        grid_rows.sort(key=lambda r: (int(float(r.get("hit_count") or 0) == 0), -float(r.get("affected_fair_value") or 0), r.get("calibration_id", "")))
    if not grid_rows:
        raise DiagnosticCalibrationError("No calibration grid row found. Run calibration first.")
    selected_grid = grid_rows[0]
    calibration_id = selected_grid["calibration_id"]
    selected_findings = [r for r in findings if r.get("calibration_id") == calibration_id]
    selected_findings.sort(
        key=lambda r: (
            -float(r.get("metric_value") or 0),
            -float(r.get("affected_fair_value") or 0),
            r.get("granularity_key", ""),
        )
    )
    top_findings = selected_findings[:top_n]
    ciks = {r.get("cik", "") for r in top_findings}
    quarters = {r.get("quarter", "") for r in top_findings} | {r.get("prior_quarter", "") for r in top_findings}
    positions = {r.get("position_id", "") for r in top_findings if r.get("position_id")}

    holdings_path = output_dir / "private_markets_holdings.csv"
    validation_path = output_dir / "validation_rules_detail.csv"
    source_rows = {
        "holdings_rows": _matching_rows(
            holdings_path,
            lambda r: r.get("cik", "") in ciks
            and (r.get("quarter", "") in quarters or r.get("report_date", "") in quarters)
            and (not positions or r.get("position_id", "") in positions or r.get("issuer_name", "") in {f.get("issuer_name", "") for f in top_findings}),
            limit=max(50, top_n * 10),
        ),
        "overlapping_validation_rule_findings": _matching_rows(
            validation_path,
            lambda r: r.get("cik", "") in ciks
            and (r.get("quarter", "") in quarters or r.get("report_date", "") in quarters),
            limit=max(50, top_n * 5),
        ),
    }
    candidate = CANDIDATES[candidate_id]
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "calibration_id": calibration_id,
        "candidate_id": candidate_id,
        "created_at": now_iso(),
        "candidate": {
            "title": candidate.title,
            "version": candidate.version,
            "rationale": candidate.rationale,
            "status": "report_only",
            "promotion_policy": "No promote_to_fail. promote_to_warn requires reviewed historical production issue and low-noise explanation.",
        },
        "threshold": {
            "value": float(selected_grid.get("threshold_value") or 0),
            "grid_row": selected_grid,
        },
        "summary_stats": selected_grid,
        "top_findings": top_findings,
        "source_rows": source_rows,
        "current_overlapping_validation_rule_findings": source_rows["overlapping_validation_rule_findings"],
        "input_file_hashes": {
            "private_markets_holdings.csv": _artifact(holdings_path),
            "position_matches.csv": _artifact(output_dir / "position_matches.csv"),
            "position_returns.csv": _artifact(output_dir / "position_returns.csv"),
            "index_returns.csv": _artifact(output_dir / "index_returns.csv"),
            "validation_rules_detail.csv": _artifact(validation_path),
        },
        "allowed_review_actions": sorted(ALLOWED_REVIEW_ACTIONS),
    }
    bundle_path = root / "bundles" / f"{calibration_id}.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    jsonschema.validate(bundle, json.loads(_schema_path("bundle.schema.json").read_text(encoding="utf-8")))
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    manifest_path = root / "review_manifest.csv"
    manifest = _read_csv_rows(manifest_path)
    manifest = [r for r in manifest if r.get("calibration_id") != calibration_id]
    manifest.append({
        "calibration_id": calibration_id,
        "candidate_id": candidate_id,
        "threshold_value": selected_grid.get("threshold_value", ""),
        "bundle_path": display_path(bundle_path),
        "bundle_sha256": sha256_file(bundle_path),
        "top_n": top_n,
        "finding_count": len(top_findings),
        "created_at": now_iso(),
    })
    _write_csv_rows(manifest_path, sorted(manifest, key=lambda r: r["calibration_id"]), MANIFEST_COLUMNS)
    return bundle_path


def validate_review(path: Path, output_dir: Path = config.OUTPUT_DIR) -> list[str]:
    errors: list[str] = []
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"could not load review JSON: {exc}"]
    try:
        schema = json.loads(_schema_path("review.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(review, schema)
    except jsonschema.ValidationError as exc:
        errors.append(f"schema validation failed: {exc.message}")
    calibration_id = str(review.get("calibration_id", ""))
    candidate_id = str(review.get("candidate_id", ""))
    bundle_path = output_root(output_dir) / "bundles" / f"{calibration_id}.json"
    if not bundle_path.exists():
        errors.append(f"bundle is missing: {bundle_path}")
        bundle = {}
    else:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        if bundle.get("candidate_id") != candidate_id:
            errors.append("candidate_id does not match bundle")
    evidence_ids = {
        str(item.get("finding_id") or item.get("granularity_key") or "")
        for item in bundle.get("top_findings", [])
        if isinstance(item, dict)
    }
    evidence_ids.update({"top_findings", "source_rows", "overlapping_validation_rule_findings", "input_file_hashes"})
    for ref in review.get("evidence_refs", []):
        ref_id = ref.get("evidence_id") if isinstance(ref, dict) else ref
        if ref_id not in evidence_ids:
            errors.append(f"evidence_refs cites unknown evidence_id: {ref_id}")
    action = review.get("recommended_action")
    if action not in ALLOWED_REVIEW_ACTIONS:
        errors.append(f"unsupported recommended_action: {action}")
    if action == "promote_to_warn":
        text = json.dumps(review, sort_keys=True).lower()
        if "historical production issue" not in text or "low-noise" not in text:
            errors.append("promote_to_warn requires a reviewed historical production issue and low-noise explanation")
    forbidden = ["promote_to_fail", "edit generated json", "suppress validation", "widen filter"]
    text = json.dumps(review, sort_keys=True).lower()
    for term in forbidden:
        if term in text:
            errors.append(f"review contains forbidden action or unsafe shortcut: {term}")
    return errors


def validate_all_reviews(output_dir: Path = config.OUTPUT_DIR) -> list[tuple[Path, list[str]]]:
    review_dir = output_root(output_dir) / "reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    return [(path, validate_review(path, output_dir=output_dir)) for path in sorted(review_dir.glob("*.json"))]


def summarize_reviews(output_dir: Path = config.OUTPUT_DIR) -> Path:
    rows = []
    for path in sorted((output_root(output_dir) / "reviews").glob("*.json")):
        errors = validate_review(path, output_dir=output_dir)
        if errors:
            continue
        review = json.loads(path.read_text(encoding="utf-8"))
        rows.append(review)
    grouped: dict[tuple[str, str, str, str, str], int] = {}
    for row in rows:
        key = (
            row.get("calibration_id", ""),
            row.get("candidate_id", ""),
            row.get("verdict", ""),
            row.get("confidence", ""),
            row.get("recommended_action", ""),
        )
        grouped[key] = grouped.get(key, 0) + 1
    out_rows = []
    for (calibration_id, candidate_id, verdict, confidence, action), count in sorted(grouped.items()):
        eligible = "true" if action == "promote_to_warn" and confidence == "high" else "false"
        out_rows.append({
            "calibration_id": calibration_id,
            "candidate_id": candidate_id,
            "verdict": verdict,
            "confidence": confidence,
            "recommended_action": action,
            "review_count": count,
            "promote_to_warn_eligible": eligible,
        })
    return _write_csv_rows(output_root(output_dir) / "review_summary.csv", out_rows, REVIEW_SUMMARY_COLUMNS)


def cli_run_calibration(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run report-only diagnostic calibration.")
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--candidate", action="append", choices=sorted(CANDIDATES))
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    if not args.all and not args.candidate:
        parser.error("pass --candidate or --all")
    paths = run_calibration(candidate_ids=None if args.all else args.candidate, output_dir=args.output_dir)
    for path in paths.values():
        print(path)
    return 0


def cli_build_review_bundle(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build diagnostic calibration review bundle.")
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--candidate", required=True, choices=sorted(CANDIDATES))
    parser.add_argument("--calibration-id")
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args(argv)
    print(build_review_bundle(args.candidate, output_dir=args.output_dir, top_n=args.top_n, calibration_id=args.calibration_id))
    return 0


def cli_validate_review(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate diagnostic calibration review JSON.")
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    if args.all and args.review:
        parser.error("pass either --review or --all")
    if not args.all and not args.review:
        parser.error("pass --review or --all")
    total = 0
    if args.all:
        for path, errors in validate_all_reviews(output_dir=args.output_dir):
            if errors:
                total += len(errors)
                for error in errors:
                    print(f"ERROR {path.name}: {error}")
            else:
                print(f"OK {path.name}")
    else:
        for error in validate_review(args.review, output_dir=args.output_dir):
            total += 1
            print(f"ERROR: {error}")
    if total:
        print(f"FAIL: {total} validation errors")
        return 1
    print("OK")
    return 0


def cli_summarize_reviews(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize diagnostic calibration reviews.")
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    args = parser.parse_args(argv)
    print(summarize_reviews(output_dir=args.output_dir))
    return 0


__all__ = [
    "ALLOWED_REVIEW_ACTIONS",
    "CANDIDATES",
    "FINDING_COLUMNS",
    "MANIFEST_COLUMNS",
    "SUMMARY_COLUMNS",
    "THRESHOLD_GRID_COLUMNS",
    "build_review_bundle",
    "run_calibration",
    "summarize_reviews",
    "validate_review",
]
