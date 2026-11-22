-- Slice 3 Task 3 fix round 1, item 2: rows decided by step 2 of the ranking (same priority; a rule naming a filing
-- beat a rule naming only a row feature), per fund, field and winning rule, and on how many the beaten rule(s) would
-- have given a different action or scale.
select cik, field, action, parameter, count(*) as rows_decided_by_tie_break
    , count(*) filter (where not tie_break_same_effect) as different_effect
from int_field_rule
where tie_break_losers > 0
group by all
order by all
limit 50
