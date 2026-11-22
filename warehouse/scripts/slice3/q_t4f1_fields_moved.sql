-- Slice 3 Task 4 fix round 1: amount fields whose normalised value, action, status, reason or read rule changed since
-- the snapshot taken before the fixes, by fund, report date, field and the change (expected: the 85 bracket rows and
-- the 196 filer-cost rows, nothing else).
with b as (select * from read_parquet('scripts/slice3/out/t4f1_fields_before.parquet'))
, a as (
    select n.accession, n.context_id, n.field, n.cik, n.report_date, n.value, n.action, n.status, n.reason
        , r.status as read_status, r.reason as read_reason, r.value_filed as read_value, r.read_rule_id
    from int_field_normalised n
    left join int_field_read r on r.accession = n.accession and r.context_id = n.context_id and r.field = n.field
)
select a.cik, a.report_date, a.accession, a.field
    , coalesce(b.action, '-') || ' -> ' || coalesce(a.action, '-') as action_change
    , coalesce(b.status, '-') || ' -> ' || a.status as status_change
    , count(*) n, sum(coalesce(a.value, 0) - coalesce(b.value, 0)) as value_change
from a
join b on b.accession = a.accession and b.context_id = a.context_id and b.field = a.field
where a.value is distinct from b.value or a.action is distinct from b.action or a.status is distinct from b.status
   or a.reason is distinct from b.reason or a.read_rule_id is distinct from b.read_rule_id
group by all order by 1, 2, 3, 4
limit 100
