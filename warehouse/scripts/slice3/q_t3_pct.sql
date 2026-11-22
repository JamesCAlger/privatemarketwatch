-- Slice 3 Task 3: size of filed share of net assets per fund (read rows with a value).
select cik, unit, count(*) n, min(value_filed) mn, quantile_cont(value_filed, 0.5) med, max(value_filed) mx
    , count(*) filter (where abs(value_filed) > 0.5) over_half, count(*) filter (where abs(value_filed) > 1) over_one
from int_field_read where field = 'pct_of_net_assets' and status = 'read' and value_filed is not null
group by 1, 2 order by 1
limit 20
