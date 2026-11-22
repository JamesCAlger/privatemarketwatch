-- Slice 3 Task 2: fair value against int_context_feature; printed_text coverage on read rows; nil detail.
select 'fv_differs' as k, count(*) as n
from int_field_read r join int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
where r.field = 'fair_value' and (r.value_filed is distinct from cf.fair_value or r.read_rule_id is distinct from cf.fair_value_rule_id)
union all select 'read_rows', count(*) from int_field_read where status = 'read'
union all select 'read_with_printed', count(*) from int_field_read where status = 'read' and printed_text is not null
union all select 'read_nonnil_without_printed', count(*) from int_field_read where status = 'read' and not is_nil and printed_text is null
union all select 'fund_rule_fv_rows', count(*) from int_field_read where field = 'fair_value' and read_rule_id not like 'cm_%'
