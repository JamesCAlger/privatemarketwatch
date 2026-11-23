-- Slice 4 Task 1, items c and e: hand-made rows run through the tests' predicates, old and new side by side. The CTEs
-- stand in for the models; the WHERE clauses are copied from the tests. Read-only (no table is read).
--   c  tests/int_field_normalised_names_rule.sql, third branch: a normalised row with a null value and a null reason.
--      Old predicate (reason <> 'moved_to_principal') lets it pass; new (is distinct from) catches it. Row n2 (the
--      documented exception, moved_to_principal) must pass both; n3 (a value) must pass both.
--   e  tests/baseline_int_field_rule_tie_break_undecidable_loser.sql: a tie-break whose only loser is undecidable
--      (tie_break_losers 1, tie_break_same_effect null), shaped as t3 of the unit test
--      int_field_rule_tie_break_and_missing_feature. The different-effect test (same_effect = false) misses it; the
--      new test catches it. r2 (same effect true) and r3 (no tie-break) pass both.
with norm(accession, context_id, field, status, value, reason) as (
    values ('A', 'n1', 'cost', 'normalised', null::double, null::varchar)
         , ('A', 'n2', 'shares', 'normalised', null::double, 'moved_to_principal')
         , ('A', 'n3', 'cost', 'normalised', 5.0, 'applied')
)
, rule(accession, context_id, field, tie_break_losers, tie_break_same_effect) as (
    values ('W', 'r1', 'principal_amount', 1, null::boolean)
         , ('W', 'r2', 'principal_amount', 1, true)
         , ('W', 'r3', 'cost', 0, null::boolean)
)
select 'c old' as check_, context_id from norm
where status = 'normalised' and value is null and reason <> 'moved_to_principal'
union all
select 'c new', context_id from norm
where status = 'normalised' and value is null and reason is distinct from 'moved_to_principal'
union all
select 'e different_effect', context_id from rule
where tie_break_same_effect = false
union all
select 'e undecidable_loser', context_id from rule
where tie_break_losers > 0 and tie_break_same_effect is null
order by 1, 2
