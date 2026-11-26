-- Slice 5 Task 2 snapshot proof: stg_correction before (8dc29093) and after loader version 6, compared on every column
-- except correction_id (which hashes the new columns, so it changes on every row), the after side restricted to the
-- stores loaded before. Replace SNAPSHOT_DIR with the snapshot folder (snapshot_tables.py output) before running.
with b as (
    select * exclude (correction_id) from read_parquet('SNAPSHOT_DIR/stg_correction_before.parquet')
)
, a as (
    select * exclude (correction_id, row_id, add_group_id, source_file)
    from read_parquet('SNAPSHOT_DIR/stg_correction_after.parquet')
    where store not like 'agent_%'
)
select 'only before' as side, count(*) as n from (select * from b except all select * from a)
union all select 'only after', count(*) from (select * from a except all select * from b)
union all select 'before rows', count(*) from b
union all select 'after rows, old stores', count(*) from a
union all select 'after rows, agent stores', count(*) from read_parquet('SNAPSHOT_DIR/stg_correction_after.parquet') where store like 'agent_%'
