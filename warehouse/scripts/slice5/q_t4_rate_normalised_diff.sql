-- Slice 5 Task 4: rows of int_rate_normalised that differ from the BASE snapshot (taken before this task, path below
-- relative to warehouse/). Only the taker positions of int_rate_adjacent may differ. Read-only.
with b as (select * from read_parquet('../scratch/2026-11-24_slice5_t4/snap/int_rate_normalised_before.parquet'))
, a as (select * from int_rate_normalised)
select 'before' as side, * from (select * from b except all select * from a)
union all
select 'after', * from (select * from a except all select * from b)
order by context_id, field, side
