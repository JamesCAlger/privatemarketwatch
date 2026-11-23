-- Slice 3 Task 2 (spec section 7, every value names its rule): read_rule_id is a concept_map row read into the same
-- field (column read_field, slice 4 Task 2), or a fund rule of the row's fund that reads the field:
-- concept_is_fair_value for fair value, concept_is_cost for cost.
select f.accession, f.context_id, f.field, f.read_rule_id
from {{ ref('int_field_read') }} f
where f.read_rule_id is not null
  and not exists (
      select 1 from {{ ref('concept_map') }} m where m.concept_map_id = f.read_rule_id and m.read_field = f.field
  )
  and not exists (
      select 1 from {{ ref('stg_reading_rule') }} r
      where r.rule_id = f.read_rule_id and r.cik = f.cik
        and ((r.action = 'concept_is_fair_value' and f.field = 'fair_value') or (r.action = 'concept_is_cost' and f.field = 'cost'))
  )
