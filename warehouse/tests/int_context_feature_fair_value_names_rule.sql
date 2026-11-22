-- Slice 3 Task 1 (spec section 7, every value names its rule): a context where a fair-value fact was read names the
-- rule it was read under, and that rule exists: a concept_map row for the standard concept, a fund rule
-- (stg_reading_rule) for a filer concept. Lists contexts that name none, or a rule that does not resolve.
select cf.accession, cf.context_id, cf.fair_value_source, cf.fair_value_rule_id
from {{ ref('int_context_feature') }} cf
where cf.fair_value_fact_count > 0
  and (
      cf.fair_value_rule_id is null
      or (cf.fair_value_source = 'standard'
          and cf.fair_value_rule_id not in (select concept_map_id from {{ ref('concept_map') }} where field = 'fair_value'))
      or (cf.fair_value_source <> 'standard'
          and cf.fair_value_rule_id not in (select rule_id from {{ ref('stg_reading_rule') }}))
  )
