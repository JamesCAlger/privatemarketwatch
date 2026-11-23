-- Baseline (spec section 7, slice 4 Task 3): a normalised spread outside 0 to 40 percent. A finding for slice 6; a
-- sanity bound only: a value inside it is not shown to be right. Ceiling int_field_normalised_rate_bound_spread.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_normalised_rate_bound_spread']) }}
select accession, context_id, cik, report_date, value, value_filed, action, rule_id
from {{ ref('int_field_normalised') }}
where field = 'spread' and status = 'normalised' and (value < 0 or value > 40)
