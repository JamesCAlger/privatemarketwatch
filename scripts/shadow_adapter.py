"""Adapter: bring EXISTING pipeline check outputs into the unified ledger.

Warn/soft step 3. The oracle (48 A-J checks) and the validation_rules engine
(PC/IDX/T/S/R/XS/F/M/RI rules) already run and write result CSVs. Rather than
re-implement them, this adapter READS those artifacts and normalizes them into
the same tier-tagged ledger schema as the four shadow engines:

    engine | rule_name | tier | enforcement | cik | period_kind | period
          | status | metric | metric_name | n_units

Tier is assigned from a tight-check map derived from validation_inventory.md;
everything else is weak. Status is taken as-reported (pass/warn/fail/skip). These
are ingested as-is from the latest run on disk (may be stale -- the ledger row
reflects whatever the last pipeline run wrote).

Read-only. Returns SELECT fragments the runner unions into the ledger.
"""

from __future__ import annotations

import logging

from pipeline.config import (
    ORACLE_CHECK_RESULTS_FILE,
    ROW_VALIDATION_ISSUES_FILE,
    SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE,
    SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE,
    VALIDATION_RULES_AGGREGATE_FILE,
)

logger = logging.getLogger("shadow_adapter")

# Tight = source-reconciliation or algebraic identity (from validation_inventory).
TIGHT_ORACLE = {"A01", "A04", "E01", "E02", "E04", "E07", "G02", "H01", "H05"}
TIGHT_VRULES = {"PC02", "PC03", "PC08", "R07", "R10", "IDX14",
                "XS01", "XS03", "XS04", "XS05", "XS06",
                "RI01", "RI02", "RI03", "RI04", "RI05", "RI06", "RI07"}


def _in(ids: set[str]) -> str:
    return ", ".join(f"'{x}'" for x in sorted(ids))


def _oracle_select() -> str | None:
    f = ORACLE_CHECK_RESULTS_FILE
    if not f.exists():
        logger.info("adapter: oracle check_results absent -- skip")
        return None
    return f"""
    SELECT 'oracle' AS engine, check_id AS rule_name,
           CASE WHEN check_id IN ({_in(TIGHT_ORACLE)}) THEN 'tight' ELSE 'weak' END AS tier,
           'advisory' AS enforcement,
           COALESCE(CAST(cik AS VARCHAR), '(global)') AS cik,
           'report_date' AS period_kind,
           COALESCE(CAST(report_date AS VARCHAR), '') AS period,
           lower(status) AS status,
           TRY_CAST(metric_value AS DOUBLE) AS metric, 'oracle_metric' AS metric_name,
           COALESCE(TRY_CAST(detail_rows AS BIGINT), TRY_CAST(residual_rows AS BIGINT), 0) AS n_units,
           CAST(NULL AS VARCHAR) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    """


def _vrules_select() -> str | None:
    f = VALIDATION_RULES_AGGREGATE_FILE
    if not f.exists():
        logger.info("adapter: validation_rules_aggregate absent -- skip")
        return None
    # validation_rules is a global per-rule aggregate (no per-CIK grain).
    return f"""
    SELECT 'validation_rules' AS engine, rule_id AS rule_name,
           CASE WHEN rule_id IN ({_in(TIGHT_VRULES)}) THEN 'tight' ELSE 'weak' END AS tier,
           CASE WHEN lower(CAST(promoted AS VARCHAR)) IN ('true','1') THEN 'blocking_eligible' ELSE 'advisory' END AS enforcement,
           '(global)' AS cik, 'global' AS period_kind,
           COALESCE(CAST(run_timestamp AS VARCHAR), '') AS period,
           CASE WHEN lower(status) IN ('skipped','skip') THEN 'skip' ELSE lower(status) END AS status,
           TRY_CAST(hit_rate AS DOUBLE) AS metric, 'hit_rate' AS metric_name,
           COALESCE(TRY_CAST(hit_count AS BIGINT), 0) AS n_units,
           CAST(NULL AS VARCHAR) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    """


def _source_recon_select() -> str | None:
    """Tight source-fact reconciliation residuals, classified by mechanism.

    Replaces the coarse per-CIK-quarter metrics ingestion with the RICH residual
    artifacts so the panel inherits source_reconciliation's own classification:
      - residual_classification.csv: output-side residuals (blocking_issue, mechanism,
        confidence, affected_source_fair_value).
      - source_only_detail.csv: source-only residuals (is_blocking, mechanism,
        confidence, source_fair_value).

    Emits ONE ledger row per (cik, report_date, mechanism) for BLOCKING residuals
    only -- the `documented_*` mechanisms are intentional scope exclusions
    (comparative periods, no-FV, source rollups, money-market, affiliation dedup)
    and are not flags. `mechanism` and `src_confidence` are carried so the runner's
    confidence/surface layer can defer to source_reconciliation's own judgement
    rather than the generic bootstrap heuristic.
    """
    res = SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE
    so = SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE
    parts: list[str] = []
    if res.exists():
        parts.append(f"""
            SELECT 'rc' AS src, CAST(cik AS VARCHAR) AS cik, CAST(report_date AS VARCHAR) AS report_date,
                   CAST(mechanism AS VARCHAR) AS mechanism,
                   CAST(blocking_issue AS BOOLEAN) AS blocking,
                   CAST(confidence AS VARCHAR) AS confidence,
                   TRY_CAST(affected_source_fair_value AS DOUBLE) AS fv
            FROM read_csv_auto('{res.as_posix()}', sample_size=-1)""")
    if so.exists():
        parts.append(f"""
            SELECT 'so' AS src, CAST(cik AS VARCHAR) AS cik, CAST(report_date AS VARCHAR) AS report_date,
                   CAST(mechanism AS VARCHAR) AS mechanism,
                   CAST(is_blocking AS BOOLEAN) AS blocking,
                   CAST(confidence AS VARCHAR) AS confidence,
                   TRY_CAST(source_fair_value AS DOUBLE) AS fv
            FROM read_csv_auto('{so.as_posix()}', sample_size=-1)""")
    if not parts:
        logger.info("adapter: source_reconciliation residual artifacts absent -- skip")
        return None
    union = " UNION ALL ".join(parts)
    # The two artifacts are two VIEWS of the same residual (output-side vs source-side),
    # keyed by (cik, report_date, mechanism). Sum FV within each view, then take the max
    # ACROSS views so a residual present in both is not double-counted.
    return f"""
    SELECT 'source_recon' AS engine, mechanism AS rule_name,
           'tight' AS tier, 'advisory' AS enforcement,
           cik, 'report_date' AS period_kind, report_date AS period,
           'fail' AS status,
           round(max(view_fv) / 1e6, 2) AS metric, 'affected_fv_m' AS metric_name,
           sum(n_view) AS n_units,
           mechanism AS mechanism, any_value(confidence) AS src_confidence
    FROM (
        SELECT cik, report_date, mechanism, src, any_value(confidence) AS confidence,
               sum(COALESCE(fv, 0)) AS view_fv, count(*) AS n_view
        FROM ({union})
        WHERE blocking
        GROUP BY cik, report_date, mechanism, src
    )
    GROUP BY cik, report_date, mechanism
    """


def _row_issues_select() -> str | None:
    """Per-row validation issues from validate_holdings (the row-grain the engines lack).

    `row_validation_issues.csv` logs only OPEN issues, so `status` is always OPEN --
    the verdict lives in `severity` (FAIL/WARN/INFO), the certainty in
    `evidence_strength` (STRONG/MODERATE/WEAK), and `action=BLOCK_VERIFIED` is
    production's own verified-blocker disposition. Aggregated to one ledger row per
    (cik, report_date, rule_id); `mechanism` carries the block-verified flag and
    `src_confidence` carries the evidence strength so the runner can defer to this
    artifact's own grading rather than the generic bootstrap heuristic.
    """
    f = ROW_VALIDATION_ISSUES_FILE
    if not f.exists():
        logger.info("adapter: row_validation_issues absent -- skip")
        return None
    return f"""
    SELECT 'row_validation' AS engine, CAST(rule_id AS VARCHAR) AS rule_name,
           CASE WHEN bool_or(upper(severity) = 'FAIL') THEN 'tight' ELSE 'weak' END AS tier,
           CASE WHEN bool_or(upper(action) = 'BLOCK_VERIFIED') THEN 'blocking_eligible'
                ELSE 'advisory' END AS enforcement,
           COALESCE(CAST(cik AS VARCHAR), '(global)') AS cik,
           'report_date' AS period_kind,
           COALESCE(CAST(report_date AS VARCHAR), '') AS period,
           CASE WHEN bool_or(upper(severity) = 'FAIL') THEN 'fail'
                WHEN bool_or(upper(severity) = 'WARN') THEN 'warn'
                ELSE 'skip' END AS status,
           CAST(count(*) AS DOUBLE) AS metric, 'issue_rows' AS metric_name,
           count(*) AS n_units,
           CASE WHEN bool_or(upper(action) = 'BLOCK_VERIFIED') THEN 'block_verified'
                ELSE lower(any_value(action)) END AS mechanism,
           lower(any_value(evidence_strength)) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    GROUP BY rule_id, cik, report_date
    """


def adapter_selects() -> list[str]:
    """Return normalized ledger-schema SELECT fragments for every available source."""
    return [s for s in (_oracle_select(), _vrules_select(), _source_recon_select(),
                        _row_issues_select()) if s]
