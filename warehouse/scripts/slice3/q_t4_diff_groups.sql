-- Slice 3 Task 4 (exploration): every non-equal pair on rows both sides have, grouped by fund, basis, field, outcome,
-- the new side's action, status and reason, and whether production's corrected_fields names the field.
with b as (
    select c.basis, c.accession, c.context_id, c.cik, c.report_date
    from cmp_row_set c where c.side = 'both'
)
, p as (
    select h.accession_number as accession, h.src_context_id as context_id, h.fair_value, h.cost_reported
        , h.principal_amount, h.principal_amount_usd, h.shares_held, h.pct_of_net_assets, h.corrected_fields
        , h.principal_fx_status
    from stg_holdings h where h.src_context_id is not null
)
, pairs as (
    select b.*, f.field, n.value as v_new, n.action, n.status, n.reason, p.corrected_fields, p.principal_fx_status
        , case f.field when 'fair_value' then p.fair_value when 'cost' then p.cost_reported
            when 'principal_amount' then p.principal_amount when 'principal_amount_usd' then p.principal_amount_usd
            when 'shares' then p.shares_held when 'pct_of_net_assets' then p.pct_of_net_assets end as v_prod
    from b
    cross join (values ('fair_value'), ('cost'), ('principal_amount'), ('principal_amount_usd'), ('shares'), ('pct_of_net_assets')) f(field)
    join p on p.accession = b.accession and p.context_id = b.context_id
    left join int_field_normalised n on n.accession = b.accession and n.context_id = b.context_id and n.field = f.field
)
, o as (
    select *
        , case when v_new is not null and v_prod is not null and abs(v_new - v_prod) < 1 then 'equal'
               when v_new is not null and v_prod is not null then 'differs'
               when v_new is null and v_prod is not null then 'new_empty'
               when v_new is not null then 'production_empty' else 'both_empty' end as outcome
    from pairs
)
select cik, basis, field, outcome, action, status, reason
    , coalesce(regexp_matches(coalesce(corrected_fields, ''), '(^|;)' || case field when 'shares' then 'shares_held' else field end || '([;:=]|$)'), false) as prod_corrected_field
    , principal_fx_status
    , count(*) n, sum(v_new - v_prod) as sum_diff
from o where outcome not in ('equal', 'both_empty')
group by all order by 1, 2, 3, 4, n desc
limit 300
