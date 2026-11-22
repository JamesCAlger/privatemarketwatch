-- Slice 3 Task 4 (exploration): the non-equal pairs of one fund and field, row by row, with the production columns
-- that may explain them. Variables: cik, field (fair_value, cost, principal_amount, principal_amount_usd, shares,
-- pct_of_net_assets).
with b as (
    select c.basis, c.accession, c.context_id, c.cik, c.report_date
    from cmp_row_set c where c.side = 'both' and c.cik = getvariable('cik')
)
, p as (
    select h.accession_number as accession, h.src_context_id as context_id, h.fair_value, h.cost_reported
        , h.principal_amount, h.principal_amount_currency, h.principal_amount_usd, h.shares_held, h.pct_of_net_assets
        , h.corrected_fields, h.principal_fx_status, h.issuer_name, h.asset_category
    from stg_holdings h where h.src_context_id is not null
)
, pairs as (
    select b.*, n.value as v_new, n.value_filed, n.currency as cur_new, n.action, n.status, n.reason, n.fx_rate, n.fx_rate_date
        , p.corrected_fields, p.principal_fx_status, p.principal_amount_currency as cur_prod, p.issuer_name, p.asset_category
        , case getvariable('field') when 'fair_value' then p.fair_value when 'cost' then p.cost_reported
            when 'principal_amount' then p.principal_amount when 'principal_amount_usd' then p.principal_amount_usd
            when 'shares' then p.shares_held when 'pct_of_net_assets' then p.pct_of_net_assets end as v_prod
        , p.principal_amount as prod_principal
    from b
    join p on p.accession = b.accession and p.context_id = b.context_id
    left join int_field_normalised n on n.accession = b.accession and n.context_id = b.context_id and n.field = getvariable('field')
)
select basis, report_date, accession, context_id, v_new, v_prod, value_filed, cur_new, cur_prod, prod_principal, fx_rate, fx_rate_date
    , action, status, reason, principal_fx_status, asset_category, left(issuer_name, 50) as issuer, corrected_fields
from pairs
where not (v_new is not null and v_prod is not null and abs(v_new - v_prod) < 1)
  and not (v_new is null and v_prod is null)
order by report_date, accession, context_id
