-- Slice 3 Task 2 (spec section 7, every value names its rule): read_rule_id is a concept_map row of the same field, or
-- (fair value only) a fund rule concept_is_fair_value of the row's fund.
select f.accession, f.context_id, f.field, f.read_rule_id
from {{ ref('int_field_read') }} f
where f.read_rule_id is not null
  and not exists (
      select 1 from {{ ref('concept_map') }} m where m.concept_map_id = f.read_rule_id and m.field = f.field
  )
  and not exists (
      select 1 from {{ ref('stg_reading_rule') }} r
      where r.rule_id = f.read_rule_id and r.action = 'concept_is_fair_value' and r.cik = f.cik and f.field = 'fair_value'
  )
