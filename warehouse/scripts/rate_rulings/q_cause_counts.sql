-- Rate rulings A and B: open rows of cmp_rate per basis, field, outcome, cause and detail (for the ceilings).
-- Run with scripts/slice2/run_sql.py.
select basis, field, outcome, cause, cause_detail, count(*) as n
from cmp_rate
where outcome in ('differs', 'new_empty', 'production_empty')
group by all
order by 1, 2, 4, 5, 3
