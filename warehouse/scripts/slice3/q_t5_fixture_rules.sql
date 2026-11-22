-- Slice 3 Task 5: for the CI fixture's non-absent amount fields, the rule origin, the read rule and the rate used.
-- Diagnostic only.
select n.context_id, n.field, r.origin, r.priority, d.read_rule_id, cm.concept_map_id, rr.action as read_rule_action
     , n.fx_rate, n.fx_rate_date
from main.int_field_normalised n
left join main.int_field_rule r using (accession, context_id, field)
left join main.int_field_read d using (accession, context_id, field)
left join main.concept_map cm on cm.concept_map_id = d.read_rule_id
left join main.stg_reading_rule rr on rr.rule_id = d.read_rule_id
where n.cik = '0000000001' and n.status <> 'absent'
order by try_cast(substr(n.context_id, 3) as integer), n.field
limit 100
