-- Slice 3 Task 4 fix round 1: every amount field of int_field_read and int_field_normalised, to list what the fixes
-- move.
select n.accession, n.context_id, n.field, n.cik, n.report_date, n.value, n.action, n.status, n.reason
    , r.status as read_status, r.reason as read_reason, r.value_filed as read_value, r.read_rule_id
from int_field_normalised n
left join int_field_read r on r.accession = n.accession and r.context_id = n.context_id and r.field = n.field
