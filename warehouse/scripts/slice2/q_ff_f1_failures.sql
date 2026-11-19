-- Final fix wave F1: the stored failing rows of the two wrapper drift tests (from the last run of each).
select 'production_wrapper_changed' as test, cik, copied_sha256 as recorded, current_sha256 as now
from main_dbt_test__audit.baseline_production_wrapper_changed
union all
select 'wrapper_copy_changed_since_load', cik, loaded_copy_sha256, copy_sha256
from main_dbt_test__audit.baseline_wrapper_copy_changed_since_load
