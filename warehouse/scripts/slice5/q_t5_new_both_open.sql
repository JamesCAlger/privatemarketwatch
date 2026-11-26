-- Slice 5 Task 5: open comparison rows (amounts and rates) on the rows that are on both sides only since this task:
-- contexts a correction makes a position, and adopted pairs joined to production's giver context. Read-only.
with nb as (
    select basis, accession, context_id, production_context_id, cik, report_date, row_reason
    from cmp_row_set
    where side = 'both' and (row_reason <> 'filed' or production_context_id <> context_id)
)
select 'amount' as model, nb.row_reason, nb.production_context_id <> nb.context_id as pair, a.cik, a.report_date,
    a.accession, a.context_id, a.field, a.outcome, a.cause, a.cause_detail,
    cast(a.value_new as varchar) as new, cast(a.value_production as varchar) as prod, a.currency_new, a.currency_production
from cmp_amount a join nb using (accession, context_id)
where a.cause is not null
union all
select 'rate', nb.row_reason, nb.production_context_id <> nb.context_id, r.cik, r.report_date, r.accession, r.context_id,
    r.field, r.outcome, r.cause, r.cause_detail,
    coalesce(cast(r.value_new as varchar), cast(r.date_new as varchar), r.text_new),
    coalesce(cast(r.value_production as varchar), cast(r.date_production as varchar), r.text_production), null, null
from cmp_rate r join nb using (accession, context_id)
where r.cause is not null
order by 1, 2, 4, 6, 7, 8
