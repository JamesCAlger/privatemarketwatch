-- Slice 5 Task 4: rows of cmp_row_set that differ from the BASE snapshot. Read-only.
with b as (select * from read_parquet('../scratch/2026-11-24_slice5_t4/snap/cmp_row_set_before.parquet'))
, a as (select * from cmp_row_set)
select 'before' as side, accession, context_id, basis, side as row_side, cause, cause_detail from (select * from b except all select * from a)
union all
select 'after', accession, context_id, basis, side, cause, cause_detail from (select * from a except all select * from b)
order by 3, 1
