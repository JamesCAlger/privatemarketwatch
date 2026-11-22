-- Final fix wave F4: cost is read in two places. int_context_feature.cost reads the standard concept only (and feeds
-- the subtotal rule, int_role_subtotal); int_field_read also reads a filer's own concept under a fund rule
-- concept_is_cost. On every position row the two must be equal, except rows read under a concept_is_cost rule (those
-- are counted, with a ceiling, by tests/baseline_int_field_read_cost_filer_concept.sql). Ceiling 0: any other
-- difference fails.
select f.accession, f.context_id, f.status, f.value_filed, cf.cost, f.read_rule_id
from {{ ref('int_field_read') }} f
join {{ ref('int_context_feature') }} cf on cf.accession = f.accession and cf.context_id = f.context_id
left join {{ ref('stg_reading_rule') }} r on r.rule_id = f.read_rule_id and r.action = 'concept_is_cost'
where f.field = 'cost'
  and r.rule_id is null
  and f.value_filed is distinct from cf.cost
