-- Slice 5 Task 5: the two adopted pairs whose production row keeps the giver's context id. Production's row (amount
-- columns and sources) and this layer's corrected amounts on the taker. Read-only.
select 'production' as side, h.accession_number, h.src_context_id, h.bdc_investment_identifier, h.fair_value,
    h.principal_amount, h.principal_amount_currency, h.principal_amount_usd, h.src_transforms,
    h.src_filled_fields, h.corrected_fields, null as layer_currency
from stg_holdings h
where (h.accession_number, h.src_context_id) in (('0001287750-25-000020', 'c-1727'), ('0001287750-25-000038', 'c-1775'),
                                                ('0001287750-25-000020', 'c-1728'), ('0001287750-25-000038', 'c-1776'))
union all
select 'layer', f.accession, f.context_id, cf.identifier_label, null, f.value, f.currency, null, f.action, f.status,
    f.reason, f.currency_normalised
from int_field_corrected f
join int_context_feature cf on cf.accession = f.accession and cf.context_id = f.context_id
where f.field = 'principal_amount'
  and (f.accession, f.context_id) in (('0001287750-25-000020', 'c-1728'), ('0001287750-25-000038', 'c-1776'))
