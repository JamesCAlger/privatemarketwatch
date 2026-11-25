-- Slice 5 Task 6, CI fixture: the stored failures of ci_fixture_expected_roles and the role of the two new contexts.
-- Run with scripts/slice5/run_sql_db.py against a fixture work folder's ci.duckdb.
select 'failure' as what, * from main_dbt_test__audit.ci_fixture_expected_roles
