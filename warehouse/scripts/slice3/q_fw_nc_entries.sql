-- Slice 3 final fix wave F2: needs_correction rows of cmp_amount with no same-field correction whose value equals
-- production's (the six indirect rows and the fourteen shares rows with a non-numeric value), with every covering
-- correction entry (read-only).
with nc as (
    select a.basis, a.accession, a.context_id, a.field, a.cik, a.report_date, a.outcome, a.value_new, a.value_production
        , a.currency_new, a.currency_production, a.cause_detail
    from main.cmp_amount a
    where a.cause = 'needs_correction'
)
, prod as (
    select accession_number as accession, src_context_id as context_id, bdc_investment_identifier, corrected_fields
    from main.stg_holdings where src_context_id is not null
)
, cover(field, correction_field) as (
    values ('fair_value', 'fair_value'), ('cost', 'cost'), ('cost', 'cost_currency'),
        ('principal_amount', 'principal_amount'),
        ('principal_amount_currency', 'principal_amount_currency'), ('principal_amount_currency', 'principal_amount'),
        ('principal_amount_usd', 'principal_amount_usd'), ('principal_amount_usd', 'principal_amount'),
        ('principal_amount_usd', 'principal_amount_currency'), ('principal_amount_usd', 'principal_fx_rate_to_usd'),
        ('principal_amount_usd', 'principal_fx_status'), ('shares', 'shares_held'), ('pct_of_net_assets', 'pct_of_net_assets')
)
select nc.basis, nc.cik, nc.report_date, nc.accession, nc.context_id, nc.field, nc.outcome, nc.cause_detail
    , nc.value_new, nc.value_production, nc.currency_new, nc.currency_production
    , c.correction_id, c.store, c.field as corr_field, c.value as corr_value, c.value_unit, c.expected_value, c.reason
    , p.corrected_fields, p.bdc_investment_identifier
from nc
join prod p on p.accession = nc.accession and p.context_id = nc.context_id
join cover cc on cc.field = nc.field
join main.stg_correction c
    on c.kind = 'value' and c.field = cc.correction_field and c.accession = nc.accession
    and (c.context_id = nc.context_id or (c.context_id is null and c.identifier = p.bdc_investment_identifier))
where (nc.field in ('principal_amount_currency', 'principal_amount_usd') and nc.cause_detail = 'correction_loaded')
   or (nc.field = 'shares' and try_cast(c.value as double) is null)
order by nc.field, nc.accession, nc.context_id
limit 100
