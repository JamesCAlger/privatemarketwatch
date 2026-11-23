-- Rate rulings A and B: the published-basis comparison table of cmp_rate (equal / differs / new empty / production
-- empty / both empty) per field, and the causes of the open rows. Run with scripts/slice2/run_sql.py.
select
    field
    , count(*) filter (where outcome = 'equal') as equal
    , count(*) filter (where outcome = 'differs') as differs
    , count(*) filter (where outcome = 'new_empty') as new_empty
    , count(*) filter (where outcome = 'production_empty') as production_empty
    , count(*) filter (where outcome = 'both_empty') as both_empty
    , count(*) as rows
from cmp_rate
where basis = 'published'
group by field
order by case field when 'interest_rate' then 1 when 'interest_rate_cash' then 2 when 'pik_rate' then 3
    when 'spread' then 4 when 'maturity_date' then 5 else 6 end
