-- Slice 5 Task 5 (exploration, before the model change): cmp_amount rows equal or both empty on the normalised value
-- that the corrected value (int_field_corrected) moves away from production. Read-only.
with f as (
    select a.*, fc.value as value_corr, pc.currency as currency_corr, fc.correction_id, pc.correction_id as pcid
    from cmp_amount a
    left join int_field_corrected fc
        on fc.accession = a.accession and fc.context_id = a.context_id
        and fc.field = case when a.field = 'principal_amount_currency' then 'principal_amount' else a.field end
    left join int_field_corrected pc
        on pc.accession = a.accession and pc.context_id = a.context_id and pc.field = 'principal_amount'
    where a.outcome in ('equal', 'both_empty')
)
select basis, field, accession, context_id, outcome, value_new, value_corr, value_production, currency_new,
    currency_corr, currency_production, correction_id, pcid
from f
where case
        when field = 'principal_amount_currency' then currency_corr is distinct from currency_production
        when value_corr is null and value_production is null then false
        when value_corr is null or value_production is null then true
        when field in ('shares', 'pct_of_net_assets') then abs(value_corr - value_production) > 0.000001
        else abs(value_corr - value_production) >= 1
      end
order by 1, 2, 3, 4
