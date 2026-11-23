-- Baseline (spec section 7, D5; slice 4 Task 2): position rows whose maturity_date could not be decided (two different values,
-- one number in two units, or a fact with no value). The value is left empty. Ceiling int_field_read_unresolved_maturity_date.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_read_unresolved_maturity_date']) }}
select accession, context_id, cik, report_date, reason, fact_count, read_rule_id
from {{ ref('int_field_read') }}
where field = 'maturity_date' and status = 'unresolved'
