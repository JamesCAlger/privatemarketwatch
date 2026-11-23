-- Slice 4 Task 4 ruling change: cmp_rate rows that moved, before (snapshot of the build at 990713e6) against now,
-- per fund, field, old outcome and cause, new outcome and cause. Snapshot path relative to warehouse/.
with b as (
    select * from read_parquet('../scratch/2026-11-23_slice4_t4/rc/cmp_rate_before.parquet')
)
select a.cik, a.basis, a.field
    , b.outcome as outcome_before, coalesce(b.cause || '|' || b.cause_detail, '-') as cause_before
    , a.outcome as outcome_now, coalesce(a.cause || '|' || a.cause_detail, '-') as cause_now
    , count(*) as n
from cmp_rate a
join b on b.accession = a.accession and b.context_id = a.context_id and b.field = a.field
where a.outcome is distinct from b.outcome or a.cause_detail is distinct from b.cause_detail
   or a.value_new is distinct from b.value_new or a.text_new is distinct from b.text_new
group by all
order by 1, 2, 3, 4, 5, 6, 7
