-- Slice 4 Task 1, item e (parked from slice 3): a tie-break (step 2 of the ranking in int_field_rule: at the same
-- priority, a rule naming a filing beats one naming only a row feature) where every beaten rule is undecidable (a
-- feature it needs is missing). tie_break_same_effect is then null, so the different-effect test
-- (tests/baseline_int_field_rule_tie_break_different_effect.sql) cannot see it: whether the beaten rule would have
-- done the same is unknown. Spec section 5
-- rule 2 makes a missing row feature an error, so such a row is not silently accepted. Measured 2026-11-23: 0 rows.
-- A rule, not a measurement. Ceiling int_field_rule_tie_break_undecidable_loser.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_rule_tie_break_undecidable_loser']) }}
select accession, context_id, field, cik, report_date, rule_id, action, value_scale, tie_break_losers
from {{ ref('int_field_rule') }}
where tie_break_losers > 0 and tie_break_same_effect is null
