-- Slice 5 Task 3 proof: amount fields whose corrected value differs from the normalised value (or whose status moved),
-- per fund, field, published or not, row reason and field reason, with the total change in value.
select f.cik, f.field, r.is_published, r.row_reason, f.status, f.reason
    , count(*) as rows_
    , sum(coalesce(f.value, 0) - coalesce(f.value_normalised, 0)) as total_change
    , count(*) filter (where f.value is distinct from f.value_normalised) as value_differs
from main.int_field_corrected f
join main.int_row_corrected r on r.accession = f.accession and r.context_id = f.context_id
where f.field in ('fair_value', 'cost', 'principal_amount', 'principal_amount_usd', 'shares', 'pct_of_net_assets')
  and (f.value is distinct from f.value_normalised or f.status in ('corrected', 'withdrawn')
       or f.currency is distinct from f.currency_normalised or f.fx_rate is distinct from f.fx_rate_normalised)
group by all
order by 1, 2, 3, 4, 5, 6
