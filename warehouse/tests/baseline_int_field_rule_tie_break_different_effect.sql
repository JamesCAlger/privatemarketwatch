-- Final fix wave F3: a tie-break (step 2 of the ranking in int_field_rule: at the same priority, a rule naming a filing
-- beats one naming only a row feature) decided between rules that would give a different action or scale. Spec
-- section 5 calls two equally specific rules an error; step 2 is a controller ruling (slice 3 Task 3 fix round 1) and
-- is safe only while the beaten rules would have done the same. An undecidable loser is left out (it has no scale).
-- Measured 2026-11-22: 0 of 462 tie-broken rows per field (principal and shares). Ceiling
-- int_field_rule_tie_break_different_effect.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_rule_tie_break_different_effect']) }}
select accession, context_id, field, cik, report_date, rule_id, action, value_scale, tie_break_losers
from {{ ref('int_field_rule') }}
where tie_break_same_effect = false
