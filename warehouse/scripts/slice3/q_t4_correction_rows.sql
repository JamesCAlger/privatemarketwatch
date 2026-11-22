-- Slice 3 Task 4: needs_correction rows of cmp_amount per fund, field and store of the covering correction, with
-- one example correction's value and reason (first 160 characters).
with nc as (
    select a.*, h.bdc_investment_identifier
    from cmp_amount a
    join stg_holdings h on h.accession_number = a.accession and h.src_context_id = a.context_id
    where a.cause = 'needs_correction'
)
select nc.cik, nc.field, c.store, c.field as correction_field, count(distinct nc.accession || nc.context_id) n_rows
    , min(nc.accession || ' ' || nc.context_id) as an_example
    , min(c.value) as a_value, left(min(c.reason), 160) as a_reason
from nc
join stg_correction c
    on c.kind = 'value' and c.accession = nc.accession
    and (c.context_id = nc.context_id or (c.context_id is null and c.identifier = nc.bdc_investment_identifier))
where c.field in ('fair_value', 'cost', 'cost_currency', 'principal_amount', 'principal_amount_currency', 'principal_amount_usd',
                  'principal_fx_rate_to_usd', 'principal_fx_status', 'shares_held', 'pct_of_net_assets')
group by all order by 1, 2, 3, 4
limit 100
