-- Baseline (spec D5): contexts whose role could not be decided. They are left out of the published set.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_source_row_unresolved']) }}
select accession, context_id, cik, report_date, role_rule, reason
from {{ ref('int_source_row') }}
where role = 'unresolved'
