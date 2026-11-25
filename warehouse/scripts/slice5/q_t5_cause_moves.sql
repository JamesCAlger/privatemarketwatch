-- Slice 5 Task 5: every comparison row whose cause or detail changed in this task, counted by before -> after
-- (before = the snapshot taken at the start of the task, scratch/2026-11-25_slice5_t5/snap). A row only on one side of
-- the change shows 'absent'. Read-only.
with b_amount as (select * from read_parquet('../scratch/2026-11-25_slice5_t5/snap/cmp_amount_before.parquet'))
, b_rate as (select * from read_parquet('../scratch/2026-11-25_slice5_t5/snap/cmp_rate_before.parquet'))
, moves as (
    select 'cmp_amount' as model, coalesce(a.basis, b.basis) as basis, coalesce(a.field, b.field) as field,
        coalesce(b.cause || '|' || coalesce(b.cause_detail, ''), case when b.accession is null then 'absent' else 'no_cause' end) as before,
        coalesce(a.cause || '|' || coalesce(a.cause_detail, ''), case when a.accession is null then 'absent' else 'no_cause' end) as after
    from cmp_amount a
    full join b_amount b on b.accession = a.accession and b.context_id = a.context_id and b.field = a.field
    union all
    select 'cmp_rate', coalesce(a.basis, b.basis), coalesce(a.field, b.field),
        coalesce(b.cause || '|' || coalesce(b.cause_detail, ''), case when b.accession is null then 'absent' else 'no_cause' end),
        coalesce(a.cause || '|' || coalesce(a.cause_detail, ''), case when a.accession is null then 'absent' else 'no_cause' end)
    from cmp_rate a
    full join b_rate b on b.accession = a.accession and b.context_id = a.context_id and b.field = a.field
)
select model, basis, field, before, after, count(*) as n
from moves
where before <> after
group by all
order by 1, 2, 3, 4, 5
