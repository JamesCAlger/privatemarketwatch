-- Slice 3 final fix wave F4: how many of the filer-concept cost rows sit in rule 6's pool, and how many of their
-- parents' near-miss reasons involve cost (read-only).
select count(*) as filer_cost_rows
    , count(t.context_id) filter (where t.text_rule is null) as in_subtotal_pool
from int_field_read r
join stg_reading_rule rr on rr.rule_id = r.read_rule_id and rr.action = 'concept_is_cost'
left join int_role_text t on t.accession = r.accession and t.context_id = r.context_id
where r.field = 'cost' and r.status = 'read'
limit 5
