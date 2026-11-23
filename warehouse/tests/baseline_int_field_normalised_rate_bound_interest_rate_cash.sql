-- Baseline (spec section 7, slice 4 Task 3): a normalised interest_rate_cash outside 0 to 40 percent. A finding for slice 6; a
-- sanity bound only: a value inside it is not shown to be right. Ceiling int_field_normalised_rate_bound_interest_rate_cash.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_normalised_rate_bound_interest_rate_cash']) }}
select accession, context_id, cik, report_date, value, value_filed, action, rule_id
from {{ ref('int_field_normalised') }}
where field = 'interest_rate_cash' and status = 'normalised' and (value < 0 or value > 40)
