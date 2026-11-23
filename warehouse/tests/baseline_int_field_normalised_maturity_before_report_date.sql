-- Baseline (slice 4 Task 3): a maturity date, taken as filed, before the position's report date. Counted and listed,
-- not changed. Ceiling int_field_normalised_maturity_before_report_date.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_normalised_maturity_before_report_date']) }}
select accession, context_id, cik, report_date, value_date, rule_id
from {{ ref('int_field_normalised') }}
where field = 'maturity_date' and status = 'normalised' and value_date < report_date
