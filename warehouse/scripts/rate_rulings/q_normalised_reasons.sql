-- Rate rulings A and B: int_field_normalised rate rows per field, status and reason (all rows, all quarters).
-- Run with scripts/slice2/run_sql.py.
select field, status, reason, count(*) as n
from int_field_normalised
where field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
group by all
order by 1, 2, 3
