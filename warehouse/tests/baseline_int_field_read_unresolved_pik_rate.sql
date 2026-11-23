-- Baseline (spec section 7, D5; slice 4 Task 2): position rows whose pik_rate could not be decided (two different values,
-- one number in two units, or a fact with no value). The value is left empty. Ceiling int_field_read_unresolved_pik_rate.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_read_unresolved_pik_rate']) }}
select accession, context_id, cik, report_date, reason, fact_count, read_rule_id
from {{ ref('int_field_read') }}
where field = 'pik_rate' and status = 'unresolved'
