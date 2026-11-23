-- Slice 4 Task 3: units of the amount fields as read, to check that giving utr:Rate the pure unit kind moves no amount row.
select field, unit, count(*) as n
from int_field_read
where field in ('fair_value', 'cost', 'principal_amount', 'shares', 'pct_of_net_assets') and status = 'read'
group by all
order by 1, 2
