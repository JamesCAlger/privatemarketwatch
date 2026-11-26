-- Slice 5 Task 6, CI fixture: every fixture correction with its target, outcome, reason, step and values, and the
-- position rows corrections add. Run with scripts/slice5/run_sql_db.py against a fixture work folder's ci.duckdb.
select 'application' as what, c.store, c.kind, c.cik, a.accession, coalesce(a.context_id, c.context_id) as context_id
    , c.field, c.value, a.outcome, a.reason, a.applied_at_step, a.value_before, a.value_after
from main.stg_correction c
left join main.int_correction_application a on a.correction_id = c.correction_id
union all
select 'row', null, row_reason, cik, accession, context_id, null, row_correction_ids, role_filed, cast(role_rule_filed as varchar)
    , null, null, null
from main.int_row_corrected where row_reason <> 'filed'
order by 1, 2, 6, 7
