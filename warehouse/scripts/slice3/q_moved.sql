-- Slice 3 Task 1, "nothing moves": every row that differs between the snapshots taken before (out/*_before.parquet,
-- at 81a17da6) and after this task (out/*_after.parquet), for int_source_row, cmp_row_set, the pre-existing columns
-- of int_context_feature and int_role_subtotal. EXCEPT ALL both ways: a row in one snapshot and not the other.
-- Paths relative to warehouse/ (run through slice2/run_sql.py). Expected result: no rows.
select 'roles' as what, 'before_only' as side, count(*) as n from (select * from 'scripts/slice3/out/roles_before.parquet' except all select * from 'scripts/slice3/out/roles_after.parquet')
union all select 'roles', 'after_only', count(*) from (select * from 'scripts/slice3/out/roles_after.parquet' except all select * from 'scripts/slice3/out/roles_before.parquet')
union all select 'cmp', 'before_only', count(*) from (select * from 'scripts/slice3/out/cmp_before.parquet' except all select * from 'scripts/slice3/out/cmp_after.parquet')
union all select 'cmp', 'after_only', count(*) from (select * from 'scripts/slice3/out/cmp_after.parquet' except all select * from 'scripts/slice3/out/cmp_before.parquet')
union all select 'feature', 'before_only', count(*) from (select * from 'scripts/slice3/out/feature_before.parquet' except all select * from 'scripts/slice3/out/feature_after.parquet')
union all select 'feature', 'after_only', count(*) from (select * from 'scripts/slice3/out/feature_after.parquet' except all select * from 'scripts/slice3/out/feature_before.parquet')
union all select 'subtotal', 'before_only', count(*) from (select * from 'scripts/slice3/out/subtotal_before.parquet' except all select * from 'scripts/slice3/out/subtotal_after.parquet')
union all select 'subtotal', 'after_only', count(*) from (select * from 'scripts/slice3/out/subtotal_after.parquet' except all select * from 'scripts/slice3/out/subtotal_before.parquet')
union all select 'roles_rows', 'before', count(*) from 'scripts/slice3/out/roles_before.parquet'
union all select 'roles_rows', 'after', count(*) from 'scripts/slice3/out/roles_after.parquet'
union all select 'cmp_rows', 'before', count(*) from 'scripts/slice3/out/cmp_before.parquet'
union all select 'cmp_rows', 'after', count(*) from 'scripts/slice3/out/cmp_after.parquet'
union all select 'feature_rows', 'before', count(*) from 'scripts/slice3/out/feature_before.parquet'
union all select 'feature_rows', 'after', count(*) from 'scripts/slice3/out/feature_after.parquet'
