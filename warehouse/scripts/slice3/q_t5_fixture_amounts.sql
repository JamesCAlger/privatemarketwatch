-- Slice 3 Task 5: every amount field of the CI fixture fund as int_field_normalised gives it, with the rule's origin.
-- Run against the fixture build's ci.duckdb with run_sql_db.py. Diagnostic only.
select n.accession, n.context_id, n.field, n.value, n.currency, n.value_filed, n.action, n.rule_id, n.status, n.reason
     , r.resolution, d.status as read_status, d.unit as read_unit
from main.int_field_normalised n
left join main.int_field_rule r using (accession, context_id, field)
left join main.int_field_read d using (accession, context_id, field)
where n.cik = '0000000001'
order by n.accession, try_cast(substr(n.context_id, 3) as integer), n.field
limit 400
