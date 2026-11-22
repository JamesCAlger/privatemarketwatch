-- Slice 3 Task 4 (exploration): non-equal pairs grouped as q_t4_diff_groups.sql, plus whether a loaded correction
-- (stg_correction, kind value) names the field on the row: by accession and context id, or by accession and identifier
-- (production's bdc_investment_identifier). Correction field names: shares_held for shares.
with b as (
    select c.basis, c.accession, c.context_id, c.cik, c.report_date
    from cmp_row_set c where c.side = 'both'
)
, p as (
    select h.accession_number as accession, h.src_context_id as context_id, h.fair_value, h.cost_reported
        , h.principal_amount, h.principal_amount_usd, h.shares_held, h.pct_of_net_assets, h.corrected_fields
        , h.principal_fx_status, h.bdc_investment_identifier
    from stg_holdings h where h.src_context_id is not null
)
, pairs as (
    select b.*, f.field, n.value as v_new, n.action, n.status, n.reason, p.corrected_fields, p.principal_fx_status
        , p.bdc_investment_identifier
        , case f.field when 'fair_value' then p.fair_value when 'cost' then p.cost_reported
            when 'principal_amount' then p.principal_amount when 'principal_amount_usd' then p.principal_amount_usd
            when 'shares' then p.shares_held when 'pct_of_net_assets' then p.pct_of_net_assets end as v_prod
        , case f.field when 'shares' then 'shares_held' else f.field end as corr_field
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
select o.cik, o.basis, o.field, o.outcome, o.action, o.reason
    , coalesce(regexp_matches(coalesce(o.corrected_fields, ''), '(^|;)' || o.corr_field || '([;:=]|$)'), false) as prod_corr
    , exists (select 1 from stg_correction c where c.kind = 'value' and c.field = o.corr_field and c.accession = o.accession
              and (c.context_id = o.context_id or (c.context_id is null and c.identifier = o.bdc_investment_identifier))) as loaded_corr
    , (select string_agg(distinct c.store, ',') from stg_correction c where c.kind = 'value' and c.field = o.corr_field and c.accession = o.accession
              and (c.context_id = o.context_id or (c.context_id is null and c.identifier = o.bdc_investment_identifier))) as stores
    , o.principal_fx_status
    , count(*) n
from o where outcome not in ('equal', 'both_empty')
group by all order by 1, 2, 3, 4, n desc
limit 300
