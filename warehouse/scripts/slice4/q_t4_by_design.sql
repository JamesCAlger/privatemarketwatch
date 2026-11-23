-- Slice 4 Task 4: where the rows this layer leaves empty on purpose (Task 3) land in cmp_rate, by this layer's
-- reason, field, basis and outcome, with the cause given. Rows outside cmp_rate (one side only, or an excluded
-- quarter) are counted as not_compared.
with n as (
    select accession, context_id, field, reason, cik, report_date
    from int_field_normalised
    where reason in ('rule_conflict', 'text_not_read', 'scale_not_decided', 'values_differ', 'pik_above_rate')
)
select n.reason, n.field, coalesce(c.basis, 'not_compared') as basis, coalesce(c.outcome, '-') as outcome,
    coalesce(c.cause || '|' || c.cause_detail, '-') as cause, count(*) as n
from n
left join cmp_rate c on c.accession = n.accession and c.context_id = n.context_id and c.field = n.field
group by all
order by 1, 2, 3, 4, 5
