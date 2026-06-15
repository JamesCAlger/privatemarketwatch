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
    SOURCE_RECONCILIATION_METRICS_FILE,
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
           COALESCE(TRY_CAST(detail_rows AS BIGINT), TRY_CAST(residual_rows AS BIGINT), 0) AS n_units
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
           COALESCE(TRY_CAST(hit_count AS BIGINT), 0) AS n_units
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    """


def _source_recon_select() -> str | None:
    f = SOURCE_RECONCILIATION_METRICS_FILE
    if not f.exists():
        logger.info("adapter: source_reconciliation_metrics absent -- skip")
        return None
    # The tight source-fact reconciliation, per CIK-quarter (cached XBRL vs output).
    return f"""
    SELECT 'source_recon' AS engine, 'source_reconciliation' AS rule_name,
           'tight' AS tier, 'advisory' AS enforcement,
           CAST(cik AS VARCHAR) AS cik, 'report_date' AS period_kind,
           CAST(report_date AS VARCHAR) AS period,
           CASE WHEN reconciliation_status = 'RECONCILED' THEN 'pass' ELSE 'fail' END AS status,
           TRY_CAST(reconciled_source_row_rate AS DOUBLE) AS metric, 'reconciled_rate' AS metric_name,
           COALESCE(TRY_CAST(blocking_issue_count AS BIGINT), 0) AS n_units
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    """


def adapter_selects() -> list[str]:
    """Return normalized ledger-schema SELECT fragments for every available source."""
    return [s for s in (_oracle_select(), _vrules_select(), _source_recon_select()) if s]
