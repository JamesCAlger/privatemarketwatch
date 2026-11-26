-- Slice 5 Task 6 Part A guard: the cmp_amount rows that changed between the snapshots before and after the review fixes
-- differ only in cause and cause_detail. Counts the changed rows by (cause, detail) before and after, and counts the
-- rows that still differ once cause and cause_detail are left out (must be 0). Reads the snapshot files written by
-- scripts/slice5/snapshot_tables.py under scratch/2026-11-25_slice5_t6/snap (run from warehouse/).
with b as (select * from read_parquet('../scratch/2026-11-25_slice5_t6/snap/cmp_amount_before.parquet'))
, a as (select * from read_parquet('../scratch/2026-11-25_slice5_t6/snap/cmp_amount_after.parquet'))
, ob as (select * from b except all select * from a)
, oa as (select * from a except all select * from b)
select 'changed before' as what, cause, cause_detail, field, count(*) as n from ob group by all
union all
select 'changed after', cause, cause_detail, field, count(*) from oa group by all
union all
select 'differ beyond cause', null, null, null, count(*) from (
    select * exclude (cause, cause_detail) from b except all select * exclude (cause, cause_detail) from a
)
order by 1, 2, 3, 4
