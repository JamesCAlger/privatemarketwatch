-- Baseline (slice 4 Task 2): position rows whose maturity date fact is not an ISO date (YYYY-MM-DD) in the filed text,
-- so maturity_date is unresolved with reason not_a_date. Also counted inside int_field_read_unresolved_maturity_date;
-- kept apart so a filer starting to write dates another way shows by name. Ceiling int_field_read_maturity_not_a_date.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_read_maturity_not_a_date']) }}
select accession, context_id, cik, report_date, reason, fact_count, read_rule_id
from {{ ref('int_field_read') }}
where field = 'maturity_date' and status = 'unresolved' and reason = 'not_a_date'
