"""Complete accepted criterion inventory, with explicit unsatisfied dependencies."""
from __future__ import annotations


# Exact scenarios retain the accepted zero-error/complete-coverage requirements.
# Numeric calibration is versioned data in contracts/working-v1.json.
CRITERIA = {
    'A1': ('Fund-quarter obligations', ['obligation_coverage', 'unknown_lifecycle_count']),
    'A2': ('Position roster completeness and purity', ['roster_fv_recall', 'roster_fv_precision', 'roster_row_recall', 'roster_row_precision', 'fund_roster_fv_floor', 'fund_roster_row_floor']),
    'A3': ('Source selection', ['source_selection_errors']),
    'A4': ('Supplemental source disposition', ['supplemental_disposition_coverage']),
    'A5': ('Accounting scope', ['accounting_scope_errors']),
    'B1': ('Target field semantics', ['target_field_contract_errors']),
    'B2': ('Field fidelity', ['amount_field_accuracy', 'other_field_accuracy']),
    'B3': ('Independent primary reconciliation', ['primary_absolute_error_ratio', 'fund_primary_error_ratio', 'primary_fund_coverage', 'primary_source_fv_coverage']),
    'B4': ('Exact public holdings partitions', ['public_partition_errors']),
    'B5': ('Rate and PIK meaning', ['rate_pik_contract_errors']),
    'C1': ('Stable entity identifiers', ['stable_entity_id_errors']),
    'C2': ('Entity resolution accuracy', ['entity_precision', 'entity_recall']),
    'C3': ('Position continuation and full chains', ['position_precision', 'position_recall', 'complete_chain_rate']),
    'C4': ('Position identity lifecycle', ['position_lifecycle_errors']),
    'D1': ('Field and metric evidence categories', ['evidence_contract_errors']),
    'D2': ('Enrichment replay', ['enrichment_replay_errors']),
    'D3': ('Sector quality and availability', ['sector_accuracy', 'sector_fv_coverage', 'sector_row_coverage']),
    'D4': ('Citation scenarios', ['citation_scenario_errors']),
    'D5': ('Evidence coverage', ['reported_amount_highlight_fv_coverage', 'reported_numeric_highlight_row_coverage', 'evidence_path_or_unavailable', 'misleading_links']),
    'E1': ('Complete product holdings access', ['accessible_holdings_difference']),
    'E2': ('Analytic definitions and denominators', ['analytic_display_errors']),
    'E3': ('Public scope and performance', ['public_scope_errors', 'product_workload_errors', 'local_citation_p95_ms']),
    'F1': ('Authoritative writers and dbt execution', ['writer_authority_errors']),
    'F2': ('Repeatability and typed parity', ['semantic_repeat_delta', 'companion_difference']),
    'F3': ('Partial failure and adoption boundary', ['release_failure_scenario_errors']),
    'F4': ('Recovery and idempotency', ['resume_scenario_errors']),
    'F5': ('Protected acceptance assets', ['acceptance_control_errors']),
    'F6': ('Migration deltas and regressions', ['unexplained_migration_delta', 'signed_quarter_regressions']),
}

EXACT_MINIMUM = {'obligation_coverage', 'supplemental_disposition_coverage'}
NUMERIC = {
    'roster_fv_recall', 'roster_fv_precision', 'roster_row_recall', 'roster_row_precision',
    'fund_roster_fv_floor', 'fund_roster_row_floor', 'amount_field_accuracy', 'other_field_accuracy',
    'primary_absolute_error_ratio', 'fund_primary_error_ratio', 'primary_fund_coverage',
    'primary_source_fv_coverage', 'entity_precision', 'entity_recall', 'position_precision',
    'position_recall', 'complete_chain_rate', 'sector_accuracy', 'sector_fv_coverage',
    'sector_row_coverage', 'reported_amount_highlight_fv_coverage',
    'reported_numeric_highlight_row_coverage', 'evidence_path_or_unavailable',
    'misleading_links', 'local_citation_p95_ms',
}
REFERENCE_REQUIRED = {
    'roster_fv_recall', 'roster_fv_precision', 'roster_row_recall', 'roster_row_precision',
    'fund_roster_fv_floor', 'fund_roster_row_floor', 'amount_field_accuracy', 'other_field_accuracy',
    'entity_precision', 'entity_recall', 'position_precision', 'position_recall',
    'complete_chain_rate', 'sector_accuracy',
}
SAMPLE_ACCURACY = REFERENCE_REQUIRED
MAXIMUM_NUMERIC = {'primary_absolute_error_ratio', 'fund_primary_error_ratio',
                   'misleading_links', 'local_citation_p95_ms'}
FRACTIONS = NUMERIC - {'misleading_links', 'local_citation_p95_ms'}
BOUNDED_FRACTIONS = FRACTIONS - {'primary_absolute_error_ratio', 'fund_primary_error_ratio'}
EXACT = {metric: {'operator': 'min' if metric in EXACT_MINIMUM else 'max',
                  'value': 1 if metric in EXACT_MINIMUM else 0}
         for _, metrics in CRITERIA.values() for metric in metrics if metric not in NUMERIC}
METRIC_UNITS = {metric: 'fraction' if metric in FRACTIONS | EXACT_MINIMUM else
               'milliseconds' if metric == 'local_citation_p95_ms' else 'count'
               for _, metrics in CRITERIA.values() for metric in metrics}
