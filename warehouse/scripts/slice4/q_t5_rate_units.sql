-- Slice 4 Task 5: the unit text int_field_read gives the rate fields, with counts (run on the warehouse or on a CI
-- fixture database). Shows which unit spellings unit_kind sees.
select field, unit, count(*) as n
from main.int_field_read
where field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread', 'pct_of_net_assets')
  and unit is not null
group by all
order by field, n desc
