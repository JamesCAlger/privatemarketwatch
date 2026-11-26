-- Slice 5 Task 4 proof: rows of int_field_corrected and int_field_normalised that differ from the BASE snapshot
-- (taken before this task), counted by field. Only rate fields may differ; on int_field_normalised only the takers of
-- int_rate_adjacent. Read-only.
with fb as (select * from read_parquet('../scratch/2026-11-24_slice5_t4/snap/int_field_corrected_before.parquet'))
, fa as (select * from read_parquet('../scratch/2026-11-24_slice5_t4/snap/int_field_corrected_after.parquet'))
, nb as (select * from read_parquet('../scratch/2026-11-24_slice5_t4/snap/int_field_normalised_before.parquet'))
, na as (select * from read_parquet('../scratch/2026-11-24_slice5_t4/snap/int_field_normalised_after.parquet'))
select 'int_field_corrected' as relation, field, count(*) as rows_changed, 0 as not_a_taker
from (select * from fa except all select * from fb) group by all
union all
select 'int_field_normalised', d.field, count(*)
    , count(*) filter (where not exists (select 1 from int_rate_adjacent a
                                         where a.accession = d.accession and a.taker_context_id = d.context_id))
from (select * from na except all select * from nb) d group by all
order by 1, 2
