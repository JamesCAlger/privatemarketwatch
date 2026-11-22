-- Slice 3 Task 4 (exploration, before cmp_amount exists): outcome counts per fund, basis and field on rows both sides
-- have. Tolerance 1 (dollar) for every numeric field here; currency compared as text.
with b as (
    select c.basis, c.accession, c.context_id, c.cik
    from cmp_row_set c where c.side = 'both'
)
, p as (
    select h.accession_number as accession, h.src_context_id as context_id, h.fair_value, h.cost_reported, h.cost
        , h.principal_amount, h.principal_amount_currency, h.principal_amount_usd, h.shares_held, h.pct_of_net_assets
    from stg_holdings h where h.src_context_id is not null
)
, pairs as (
    select b.cik, b.basis, f.field, n.value as v_new
        , case f.field when 'fair_value' then p.fair_value when 'cost' then p.cost_reported
            when 'principal_amount' then p.principal_amount when 'principal_amount_usd' then p.principal_amount_usd
            when 'shares' then p.shares_held when 'pct_of_net_assets' then p.pct_of_net_assets end as v_prod
    from b
    cross join (values ('fair_value'), ('cost'), ('principal_amount'), ('principal_amount_usd'), ('shares'), ('pct_of_net_assets')) f(field)
    join p on p.accession = b.accession and p.context_id = b.context_id
    left join int_field_normalised n on n.accession = b.accession and n.context_id = b.context_id and n.field = f.field
)
select cik, basis, field
    , count(*) filter (where v_new is not null and v_prod is not null and abs(v_new - v_prod) < 1) as equal_lt1
    , count(*) filter (where v_new is not null and v_prod is not null and abs(v_new - v_prod) >= 1) as differs
    , count(*) filter (where v_new is null and v_prod is not null) as new_empty
    , count(*) filter (where v_new is not null and v_prod is null) as production_empty
    , count(*) filter (where v_new is null and v_prod is null) as both_empty
from pairs
group by all order by 1, 2, 3
limit 200
