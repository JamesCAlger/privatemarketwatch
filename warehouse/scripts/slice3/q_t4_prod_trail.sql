-- Slice 3 Task 4 (exploration): production's own trail columns for the rows of one accession (variable acc), read
-- from the holdings Parquet directly (stg_holdings does not carry them). Read-only.
select src_context_id, fair_value, cost, principal_amount, principal_amount_currency, principal_amount_usd, shares_held
    , left(corrected_fields, 120) as corrected_fields, left(src_transforms, 200) as src_transforms
    , left(src_field_overrides, 120) as src_field_overrides, left(src_filled_fields, 80) as src_filled_fields
    , fair_value_source, cost_source
from read_parquet('../data/output/private_markets_holdings.parquet')
where accession_number = getvariable('acc')
  and (getvariable('ctx') = '' or src_context_id = getvariable('ctx'))
order by src_context_id
