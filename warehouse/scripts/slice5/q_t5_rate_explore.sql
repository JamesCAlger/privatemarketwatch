-- Slice 5 Task 5 (exploration, before the model change): every cmp_rate row whose outcome on the corrected values
-- (int_field_corrected) differs from its outcome on the normalised values, and every row still open after correction
-- that carries a correction cause. Read-only.
with f as (
    select a.*,
        fc.value as value_corr, fc.value_date as date_corr, ir.rate_kind as kind_corr, fc.status as status_corr,
        fc.reason as reason_corr, coalesce(fc.correction_id, case when a.field = 'rate_kind' then ir.correction_id end)
            as correction_id
    from cmp_rate a
    left join int_field_corrected fc
        on fc.accession = a.accession and fc.context_id = a.context_id
        and fc.field = case when a.field = 'rate_kind' then 'interest_rate' else a.field end
    left join int_field_corrected ir
        on ir.accession = a.accession and ir.context_id = a.context_id and ir.field = 'interest_rate'
)
, o as (
    select *,
        case
            when field = 'rate_kind' then
                case when kind_corr is null and text_production is null then 'both_empty'
                     when kind_corr is null then 'new_empty' when text_production is null then 'production_empty'
                     when kind_corr = text_production then 'equal' else 'differs' end
            when field = 'maturity_date' then
                case when date_corr is null and date_production is null then 'both_empty'
                     when date_corr is null then 'new_empty' when date_production is null then 'production_empty'
                     when date_corr = date_production then 'equal' else 'differs' end
            when value_corr is null and value_production is null then 'both_empty'
            when value_corr is null then 'new_empty' when value_production is null then 'production_empty'
            when abs(value_corr - value_production) <= 1e-9 then 'equal' else 'differs'
        end as outcome_corr
    from f
)
select basis, field, outcome, outcome_corr, cause, cause_detail, reason_corr, correction_id is not null as has_corr,
    count(*) as n
from o
where outcome is distinct from outcome_corr
   or (cause = 'needs_correction' and outcome_corr not in ('equal', 'both_empty'))
group by all
order by 1, 2, 3, 4, 5, 6
