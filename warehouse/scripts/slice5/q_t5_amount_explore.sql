-- Slice 5 Task 5 (exploration, before the model change): the cmp_amount rows with a correction cause, against the
-- corrected value of int_field_corrected. For the currency field, the principal row's currency. Read-only.
with c as (
    select a.*
    from cmp_amount a
    where a.cause = 'needs_correction' or a.cause_detail = 'correction_loaded_value_not_matched'
)
, f as (
    select c.*, fc.value as value_corr, fc.status as status_corr, fc.correction_id,
        pc.currency as currency_corr, pc.correction_id as principal_correction_id
    from c
    left join int_field_corrected fc
        on fc.accession = c.accession and fc.context_id = c.context_id
        and fc.field = case when c.field = 'principal_amount_currency' then 'principal_amount' else c.field end
    left join int_field_corrected pc
        on pc.accession = c.accession and pc.context_id = c.context_id and pc.field = 'principal_amount'
)
select basis, field, cause_detail,
    case
        when field = 'principal_amount_currency' then
            case when currency_corr is not distinct from currency_production then 'equal' else 'differs' end
        when value_corr is null and value_production is null then 'equal'
        when field in ('shares', 'pct_of_net_assets') and abs(value_corr - value_production) <= 0.000001 then 'equal'
        when abs(value_corr - value_production) < 1 then 'equal'
        else 'differs'
    end as after_outcome,
    correction_id is not null or (field = 'principal_amount_currency' and principal_correction_id is not null) as has_corr,
    count(*) as n
from f
group by all
order by 1, 2, 3, 4, 5
