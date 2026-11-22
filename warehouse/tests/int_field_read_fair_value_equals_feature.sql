-- Slice 3 Task 2: on every position row the fair value read here equals int_context_feature's, read under the same
-- rule. Two models reading one value must agree (ceiling 0).
select f.accession, f.context_id, f.status, f.value_filed, cf.fair_value, f.read_rule_id, cf.fair_value_rule_id
from {{ ref('int_field_read') }} f
join {{ ref('int_context_feature') }} cf on cf.accession = f.accession and cf.context_id = f.context_id
where f.field = 'fair_value'
  and (f.value_filed is distinct from cf.fair_value or f.read_rule_id is distinct from cf.fair_value_rule_id)
