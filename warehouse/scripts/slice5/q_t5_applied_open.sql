-- Slice 5 Task 5: every open comparison row whose field carries an applied correction (correction_id), with its cause.
-- The brief: open every such row before naming its cause. Read-only.
select 'amount' as model, basis, cik, report_date, accession, context_id, field, outcome, cause, cause_detail,
    cast(value_normalised as varchar) as normalised, cast(value_new as varchar) as new,
    cast(value_production as varchar) as prod, currency_normalised, currency_new, currency_production, correction_id
from cmp_amount
where correction_id is not null and cause is not null
union all
select 'rate', basis, cik, report_date, accession, context_id, field, outcome, cause, cause_detail,
    coalesce(cast(value_normalised as varchar), cast(date_normalised as varchar), text_normalised),
    coalesce(cast(value_new as varchar), cast(date_new as varchar), text_new),
    coalesce(cast(value_production as varchar), cast(date_production as varchar), text_production), null, null, null,
    correction_id
from cmp_rate
where correction_id is not null and cause is not null
order by 1, 9, 10, 3, 5, 6, 7
