-- Slice 5 Task 4: outcomes of the rate corrections (the 556 Task 3 held as deferred rate_reading_not_rerun: fields
-- interest_rate, interest_rate_cash, rate_kind, pik_rate, spread, maturity_date), by field, outcome and reason, and the
-- totals of every outcome|reason over all corrections. Read-only.
select 'rate' as part, case when value_column = 'rate_kind' then 'rate_kind' else field_row end as field, outcome, reason, count(*) as n
from int_correction_application
where field_row in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
  and step in ('reading_input', 'converted')
group by all
union all
select 'all', null, outcome, reason, count(*) from int_correction_application group by all
order by 1 desc, 2, 3, 4
