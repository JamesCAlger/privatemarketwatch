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
    AGGREGATE_HEADER_FLAGS_FILE,
    CLASSIFICATION_VALIDATION_FILE,
    DERIVATIVE_ROLE_REVIEW_FILE,
    FUND_FINANCIALS_VALIDATION_CURRENT_FILE,
    FUND_STRATEGY_VALIDATION_FILE,
    HOLDINGS_GAV_RECONCILIATION_FILE,
    HTML_TEMPLATE_VALIDATION_FILE,
    ORACLE_CHECK_RESULTS_FILE,
    OUTPUT_DIR,
    PROVENANCE_LEDGER_FILE,
    ROW_VALIDATION_ISSUES_FILE,
    SOURCE_RECONCILIATION_DETAIL_FILE,
    SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE,
    SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE,
    VALIDATION_RULES_AGGREGATE_FILE,
)

# nonaccrual_flags.csv has no config constant; build from OUTPUT_DIR locally.
NONACCRUAL_FLAGS_FILE = OUTPUT_DIR / "nonaccrual_flags.csv"

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


def _fund_financials_select() -> str | None:
    """Fund-financials validation checks (NAV, returns, balance-sheet identities).

    Unlike row_validation, `status` here is a real outcome (PASS/FAIL/SKIP); the
    rule's configured importance lives in `severity` (FAIL=hard / WARN=advisory /
    INFO / null) and certainty in `evidence_strength`. One row per
    (cik, report_date, check_code) already, so aggregation is mostly a safety net.
    tier=tight only for FAIL-severity (hard identity) checks; the runner surfaces
    failures by the check's own severity + evidence rather than the heuristic. This
    cross-checks the identity engine's nav/income/balance-sheet rules with the
    existing audited fund-financials implementation.
    """
    f = FUND_FINANCIALS_VALIDATION_CURRENT_FILE
    if not f.exists():
        logger.info("adapter: fund_financials_validation_current absent -- skip")
        return None
    period = "COALESCE(CAST(report_date AS VARCHAR), CAST(report_quarter AS VARCHAR), '')"
    return f"""
    SELECT 'fund_financials' AS engine, CAST(check_code AS VARCHAR) AS rule_name,
           CASE WHEN bool_or(upper(severity) = 'FAIL') THEN 'tight' ELSE 'weak' END AS tier,
           'advisory' AS enforcement,
           COALESCE(CAST(cik AS VARCHAR), '(global)') AS cik,
           'report_date' AS period_kind,
           {period} AS period,
           CASE WHEN bool_or(upper(status) = 'FAIL') THEN 'fail'
                WHEN bool_or(upper(status) = 'PASS') THEN 'pass'
                ELSE 'skip' END AS status,
           CAST(count(*) AS DOUBLE) AS metric, 'check_rows' AS metric_name,
           count(*) AS n_units,
           lower(any_value(mechanism)) AS mechanism,
           lower(COALESCE(any_value(evidence_strength), '')) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    GROUP BY check_code, cik, {period}
    """


def _html_template_select() -> str | None:
    """HTML-extraction validation: FV reconciliation at the extraction boundary.

    An anchor independent of source_recon (which reconciles the XBRL side) -- this
    reconciles HTML-extracted FV against companyfacts for the pre-XBRL/HTML cohort.
    Two checks per (cik, report_date): `html_agg` (extracted FV sum vs companyfacts;
    tight, FAIL surfaces via the generic tight_anchor path) and `html_carry`
    (cross-quarter carry continuity; weak -- a FAIL is mapped to a warn flag).
    """
    f = HTML_TEMPLATE_VALIDATION_FILE
    if not f.exists():
        logger.info("adapter: html_template_validation absent -- skip")
        return None
    t = f"read_csv_auto('{f.as_posix()}', sample_size=-1)"
    return f"""
    SELECT 'html_extract' AS engine, 'html_agg' AS rule_name, 'tight' AS tier,
           'advisory' AS enforcement, CAST(cik AS VARCHAR) AS cik,
           'report_date' AS period_kind, CAST(report_date AS VARCHAR) AS period,
           CASE WHEN bool_or(upper(agg_status) = 'FAIL') THEN 'fail'
                WHEN bool_or(upper(agg_status) = 'PASS') THEN 'pass' ELSE 'skip' END AS status,
           round(any_value(TRY_CAST(adj_ratio AS DOUBLE)), 3) AS metric, 'adj_ratio' AS metric_name,
           count(*) AS n_units,
           CASE WHEN bool_or(CAST(drift_detected AS BOOLEAN)) THEN 'drift'
                ELSE CAST(NULL AS VARCHAR) END AS mechanism,
           CAST(NULL AS VARCHAR) AS src_confidence
    FROM {t} GROUP BY cik, report_date
    UNION ALL
    SELECT 'html_extract', 'html_carry', 'weak', 'advisory', CAST(cik AS VARCHAR),
           'report_date', CAST(report_date AS VARCHAR),
           CASE WHEN bool_or(upper(carry_status) = 'FAIL') THEN 'warn'
                WHEN bool_or(upper(carry_status) = 'PASS') THEN 'pass' ELSE 'skip' END,
           round(any_value(TRY_CAST(carry_rate AS DOUBLE)), 3), 'carry_rate', count(*),
           CAST(NULL AS VARCHAR), CAST(NULL AS VARCHAR)
    FROM {t} GROUP BY cik, report_date
    """


def _gav_recon_select() -> str | None:
    """Holdings GAV reconciliation -- the existing, richer cross-check of the
    conservation engine (handles subsidiary positions, multiple denominators,
    aggregate-filtered scope). The runner surfaces hard FAILs and OVER_COVERAGE
    (positions exceeding the denominator -- the FV-inflation direction), but NOT
    under_coverage (incomplete extraction, an expected gap). `blocks_verified`
    marks production's own verified-blocker disposition.
    """
    f = HOLDINGS_GAV_RECONCILIATION_FILE
    if not f.exists():
        logger.info("adapter: holdings_gav_reconciliation absent -- skip")
        return None
    return f"""
    SELECT 'gav_recon' AS engine, 'gav_reconciliation' AS rule_name, 'tight' AS tier,
           CASE WHEN bool_or(CAST(blocks_verified AS BOOLEAN)) THEN 'blocking_eligible'
                ELSE 'advisory' END AS enforcement,
           CAST(cik AS VARCHAR) AS cik, 'report_date' AS period_kind,
           CAST(report_date AS VARCHAR) AS period,
           CASE WHEN bool_or(upper(reconciliation_status) = 'FAIL') THEN 'fail'
                WHEN bool_or(upper(reconciliation_status) = 'WARN') THEN 'warn'
                WHEN bool_or(upper(reconciliation_status) = 'PASS') THEN 'pass' ELSE 'skip' END AS status,
           round(any_value(TRY_CAST(residual_pct AS DOUBLE)), 2) AS metric, 'residual_pct' AS metric_name,
           count(*) AS n_units,
           CASE WHEN bool_or(flag = 'over_coverage') THEN 'over_coverage'
                WHEN bool_or(flag = 'under_coverage') THEN 'under_coverage'
                ELSE lower(any_value(flag)) END AS mechanism,
           lower(any_value(comparison_confidence)) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    GROUP BY cik, report_date
    """


def _fund_strategy_select() -> str | None:
    """Layer-3 fund identity vs holdings-mix validation (weak/advisory axis).

    `validation_status` UNDER_REVIEW -> warn flag (flows the generic weak-warn path:
    surfaces only when corroborated by a co-located tight fail). NO_REFERENCE -> skip.
    """
    f = FUND_STRATEGY_VALIDATION_FILE
    if not f.exists():
        logger.info("adapter: fund_strategy_validation absent -- skip")
        return None
    return f"""
    SELECT 'fund_strategy' AS engine, 'fund_strategy_validation' AS rule_name, 'weak' AS tier,
           'advisory' AS enforcement, CAST(cik AS VARCHAR) AS cik,
           'report_date' AS period_kind, CAST(report_date AS VARCHAR) AS period,
           CASE WHEN bool_or(upper(validation_status) = 'UNDER_REVIEW') THEN 'warn'
                WHEN bool_or(upper(validation_status) = 'PASS') THEN 'pass' ELSE 'skip' END AS status,
           round(100.0 * sum(COALESCE(TRY_CAST(affected_fair_value AS DOUBLE), 0))
                 / NULLIF(sum(COALESCE(TRY_CAST(total_fair_value AS DOUBLE), 0)), 0), 2) AS metric,
           'affected_pct' AS metric_name, count(*) AS n_units,
           lower(any_value(strategy_source)) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    GROUP BY cik, report_date
    """


def _nonaccrual_select() -> str | None:
    """Non-accrual evidence -- a PRESENCE signal, not a pass/fail check.

    Non-accrual is a credit-risk fact, not a data defect, so it is ingested as a
    weak warn (visible in the ledger, never surfaced) capturing the count of
    flagged positions per (cik, report_date) and the dominant evidence source.
    """
    f = NONACCRUAL_FLAGS_FILE
    if not f.exists():
        logger.info("adapter: nonaccrual_flags absent -- skip")
        return None
    return f"""
    SELECT 'nonaccrual' AS engine, 'nonaccrual_flag' AS rule_name, 'weak' AS tier,
           'advisory' AS enforcement, CAST(cik AS VARCHAR) AS cik,
           'report_date' AS period_kind, CAST(report_date AS VARCHAR) AS period,
           'warn' AS status,
           CAST(count(*) AS DOUBLE) AS metric, 'nonaccrual_positions' AS metric_name,
           count(*) AS n_units,
           lower(any_value(nonaccrual_source)) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    GROUP BY cik, report_date
    """


def _aggregate_header_select() -> str | None:
    """Reviewed aggregate/JV-header verdict catalog (name-keyed, no cik/period).

    Directly on the FV over-inclusion axis. The source has no cik, so `cik` holds
    the normalized issuer name (period_kind='name'). AGGREGATE_HEADER = a confirmed
    subtotal/header that should not be a position (status=fail -> surfaces by the
    review confidence); JV_SUBSIDIARY = a subsidiary holding (status=warn, not a
    defect -> not surfaced).
    """
    f = AGGREGATE_HEADER_FLAGS_FILE
    if not f.exists():
        logger.info("adapter: aggregate_header_flags absent -- skip")
        return None
    return f"""
    SELECT 'aggregate_header' AS engine, CAST(verdict AS VARCHAR) AS rule_name, 'tight' AS tier,
           'advisory' AS enforcement,
           COALESCE(CAST(name_norm AS VARCHAR), '(unknown)') AS cik,
           'name' AS period_kind, '' AS period,
           CASE WHEN upper(verdict) = 'AGGREGATE_HEADER' THEN 'fail' ELSE 'warn' END AS status,
           round(sum(COALESCE(TRY_CAST(total_fv AS DOUBLE), 0)) / 1e6, 2) AS metric, 'total_fv_m' AS metric_name,
           sum(COALESCE(TRY_CAST(n_positions AS BIGINT), 0)) AS n_units,
           lower(CAST(verdict AS VARCHAR)) AS mechanism,
           lower(any_value(confidence)) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    GROUP BY verdict, name_norm
    """


def _classification_select() -> str | None:
    """Classification cross-reference rules (10 global rules, disagreement rate).

    A rule warns when actual classifications disagree with the expected mapping at
    >=1% (weak; flows the generic weak-warn path). Global grain (no cik/period).
    """
    f = CLASSIFICATION_VALIDATION_FILE
    if not f.exists():
        logger.info("adapter: classification_validation absent -- skip")
        return None
    return f"""
    SELECT 'classification' AS engine, CAST(rule AS VARCHAR) AS rule_name, 'weak' AS tier,
           'advisory' AS enforcement, '(global)' AS cik, 'global' AS period_kind, '' AS period,
           CASE WHEN TRY_CAST(disagreement_pct AS DOUBLE) >= 1.0 THEN 'warn' ELSE 'pass' END AS status,
           TRY_CAST(disagreement_pct AS DOUBLE) AS metric, 'disagreement_pct' AS metric_name,
           COALESCE(TRY_CAST(disagreement_count AS BIGINT), 0) AS n_units,
           CAST(NULL AS VARCHAR) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    """


def _derivative_role_select() -> str | None:
    """Uncertain derivative-role positions for agentic review (analytics-only).

    The derivative_role classifier (pipeline/bdc_derivatives.py) cannot resolve
    every position to portfolio vs. financing-hedge with high confidence -- the
    residual (notional-to-debt contradictions, no-signal types) is written to
    derivative_role_review.csv. This adapter routes it through the universal panel
    like every other review step. One ledger row per (cik, report_date, mechanism);
    `src_confidence` carries the classifier's own grade so the runner defers to it.
    """
    f = DERIVATIVE_ROLE_REVIEW_FILE
    if not f.exists():
        logger.info("adapter: derivative_role_review absent -- skip")
        return None
    return f"""
    SELECT 'derivative_role' AS engine, mechanism AS rule_name,
           'tight' AS tier, 'advisory' AS enforcement,
           CAST(cik AS VARCHAR) AS cik, 'report_date' AS period_kind,
           CAST(report_date AS VARCHAR) AS period,
           'fail' AS status,
           round(sum(TRY_CAST(net_fv AS DOUBLE)) / 1e6, 2) AS metric,
           'uncertain_deriv_fv_m' AS metric_name,
           count(*) AS n_units,
           mechanism AS mechanism, lower(any_value(role_confidence)) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    GROUP BY cik, report_date, mechanism
    """


def _agent_a_select() -> str | None:
    """Agent A enrichment-corroboration flags (basis_spread vs XBRL + SOFR reconciliation).
    Aggregated per CIK-quarter; dominant reconciliation verdict carried as mechanism so B
    can prioritise (reconcile_agentA / reconcile_neither are the high-value packets)."""
    f = OUTPUT_DIR / "shadow" / "agent_a_flags.csv"
    if not f.exists():
        logger.info("adapter: agent_a_flags absent -- skip")
        return None
    return f"""
    SELECT 'agentA' AS engine, rule_name, 'tight' AS tier, 'advisory' AS enforcement,
           CAST(cik AS VARCHAR) AS cik, 'report_date' AS period_kind,
           CAST(report_date AS VARCHAR) AS period,
           CASE WHEN bool_or(lower(status) = 'fail') THEN 'fail'
                WHEN bool_or(lower(status) = 'warn') THEN 'warn' ELSE 'pass' END AS status,
           TRY_CAST(max(TRY_CAST(xbrl_residual AS DOUBLE)) AS DOUBLE) AS metric,
           'xbrl_reconcile_residual_pp' AS metric_name,
           CAST(count(*) AS BIGINT) AS n_units,
           mode(mechanism) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
    FROM read_csv_auto('{f.as_posix()}', sample_size=-1)
    GROUP BY cik, report_date, rule_name
    """


# Provenance re-verifier reason codes (pipeline/provenance_reverify.py).
# tight/fail = pointer-verification failures that belong in the blocker lane;
# weak/warn = informational states (incl. anchor_stale: re-stamp maintenance,
# not a data error); weak/pass = healthy states kept for coverage measurement.
PROV_TIGHT_FAIL = {"filing_mismatch", "anchor_missing", "provenance_wrong",
                   "source_unavailable", "transform_drift"}
PROV_WEAK_WARN = {"anchor_stale", "no_provenance", "text_pathway",
                  "merged_context_excluded"}
# everything else (verified, corrected, derived, unchecked_trivial) -> weak/pass


def _provenance_select() -> str | None:
    """Provenance re-verifier verdicts, aggregated to (cik, report_date, reason_code).

    8.1 dedup: tight-lane rows whose output_row_id matches a BLOCKING row in
    source_reconciliation_detail.csv for the same cik-report_date are excluded
    from the queue-facing groups and counted in a per-cik-quarter
    'provenance_already_queued' audit row (no silent truncation).

    The dedup surface is the MATCHED detail file (output_row_id direct identity
    join), not the source-only file. Source-only rows are UNMATCHED filing facts
    whose population is disjoint from the provenance ledger by construction.
    """
    if not PROVENANCE_LEDGER_FILE.exists():
        return None
    prov = PROVENANCE_LEDGER_FILE.as_posix()
    det = SOURCE_RECONCILIATION_DETAIL_FILE
    det_exists = det.exists()
    tight = ", ".join(f"'{c}'" for c in sorted(PROV_TIGHT_FAIL))
    warn = ", ".join(f"'{c}'" for c in sorted(PROV_WEAK_WARN))
    if det_exists:
        queued_cte = f"""
        queued AS (
            SELECT DISTINCT cik, report_date, output_row_id AS qrow
            FROM read_csv_auto('{det.as_posix()}', header=true, all_varchar=true)
            WHERE lower(COALESCE(blocking_issue, '')) IN ('true', '1')
        ),"""
    else:
        queued_cte = """
        queued AS (
            SELECT NULL::VARCHAR AS cik, NULL::VARCHAR AS report_date,
                   NULL::VARCHAR AS qrow WHERE 1=0
        ),"""
    # Wrap the CTE in a subquery so it can participate in the runner's UNION ALL
    # chain. A bare WITH ... SELECT cannot appear in UNION ALL position in DuckDB.
    return f"""
    SELECT * FROM (
        WITH {queued_cte}
        prov AS (
            SELECT p.*,
                   (q.qrow IS NOT NULL
                    AND p.reason_code IN ({tight})) AS already_queued
            FROM read_csv_auto('{prov}', header=true, all_varchar=true) p
            LEFT JOIN queued q
              ON q.cik = p.cik AND q.report_date = p.report_date
             AND q.qrow = p.row_id
        ),
        grouped AS (
            SELECT cik, report_date, reason_code,
                   COUNT(DISTINCT row_id) AS n_rows,
                   ROUND(COALESCE(SUM(CASE WHEN field = 'fair_value'
                         THEN TRY_CAST(published AS DOUBLE) END), 0) / 1e6, 2)
                       AS fv_m
            FROM prov WHERE NOT already_queued
            GROUP BY 1, 2, 3
        ),
        excluded AS (
            SELECT cik, report_date,
                   COUNT(DISTINCT row_id) AS n_rows,
                   ROUND(COALESCE(SUM(CASE WHEN field = 'fair_value'
                         THEN TRY_CAST(published AS DOUBLE) END), 0) / 1e6, 2)
                       AS fv_m
            FROM prov WHERE already_queued
            GROUP BY 1, 2
        )
        SELECT 'provenance_reverify' AS engine,
               reason_code AS rule_name,
               CASE WHEN reason_code IN ({tight}) THEN 'tight' ELSE 'weak' END AS tier,
               'advisory' AS enforcement,
               cik,
               'report_date' AS period_kind,
               report_date AS period,
               CASE WHEN reason_code IN ({tight}) THEN 'fail'
                    WHEN reason_code IN ({warn}) THEN 'warn'
                    ELSE 'pass' END AS status,
               fv_m AS metric,
               'affected_fv_m' AS metric_name,
               CAST(n_rows AS BIGINT) AS n_units,
               reason_code AS mechanism,
               CAST(NULL AS VARCHAR) AS src_confidence
        FROM grouped
        UNION ALL
        SELECT 'provenance_reverify', 'provenance_already_queued', 'weak',
               'advisory', cik, 'report_date', report_date, 'pass',
               fv_m, 'affected_fv_m', CAST(n_rows AS BIGINT),
               'dedup_source_recon', CAST(NULL AS VARCHAR)
        FROM excluded
    )"""


def adapter_selects() -> list[str]:
    """Return normalized ledger-schema SELECT fragments for every available source."""
    return [s for s in (_oracle_select(), _vrules_select(), _source_recon_select(),
                        _row_issues_select(), _fund_financials_select(),
                        _html_template_select(), _gav_recon_select(),
                        _fund_strategy_select(), _nonaccrual_select(),
                        _aggregate_header_select(), _classification_select(),
                        _derivative_role_select(), _agent_a_select(),
                        _provenance_select()) if s]
