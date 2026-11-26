-- Slice 5 Task 4: rows of int_row_corrected that differ from the BASE snapshot (rate corrections now pass the screen
-- and can supply a term field). Read-only.
with b as (select * from read_parquet('../scratch/2026-11-24_slice5_t4/snap/int_row_corrected_before.parquet'))
, a as (select * from int_row_corrected)
select 'before' as side, * from (select * from b except all select * from a)
union all
select 'after', * from (select * from a except all select * from b)
order by context_id, side
