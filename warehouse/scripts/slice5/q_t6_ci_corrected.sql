-- Slice 5 Task 6, CI fixture: int_field_corrected on the fixture rows corrections touch. Run with
-- scripts/slice5/run_sql_db.py against a fixture work folder's ci.duckdb.
select *
from main.int_field_corrected
where cik = '0000000001' and context_id in ('c-3', 'c-4', 'c-24', 'c-27', 'c-91')
  and (correction_id is not null or field in ('interest_rate', 'interest_rate_cash', 'pik_rate')
       or context_id in ('c-27', 'c-91'))
order by context_id, field
