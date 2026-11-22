-- Slice 3 Task 2: status and reason counts per field, and read_rule_id kinds.
select field, status, reason, count(*) as rows, count(distinct read_rule_id) as rules, min(read_rule_id) as a_rule, max(read_rule_id) as b_rule
from int_field_read
group by all
order by field, status, reason
