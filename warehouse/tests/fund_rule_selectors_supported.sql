-- Fund rules (rule_class fund_rule, from a wrapper's reading_rules) name selectors their action reads, and only those.
-- A selector a model does not read would be ignored, so the rule would apply more widely than written.
--   concept_is_fair_value, concept_is_term_fact : a filer, concept namespace and local name; accession and dates optional
--   subtotal_on_fair_value                       : a filer; dates optional; no selector
--   any other action                             : no concept selector (only the two concept actions read them)
select rule_id, cik, action, 'concept rule needs cik, namespace and local name, and reads no axis, member, label or feature' as problem
from {{ ref('stg_reading_rule') }}
where action in ('concept_is_fair_value', 'concept_is_term_fact')
  and (cik is null or sel_concept_namespace is null or sel_concept_local is null
       or sel_axis is not null or sel_member is not null or sel_label is not null or sel_feature is not null)
union all
select rule_id, cik, action, 'subtotal_on_fair_value needs cik and takes no selector'
from {{ ref('stg_reading_rule') }}
where action = 'subtotal_on_fair_value'
  and (cik is null or sel_accession is not null or sel_axis is not null or sel_member is not null or sel_label is not null
       or sel_feature is not null or sel_concept_namespace is not null or sel_concept_local is not null)
union all
select rule_id, cik, action, 'only concept rules read concept selectors'
from {{ ref('stg_reading_rule') }}
where action not in ('concept_is_fair_value', 'concept_is_term_fact')
  and (sel_concept_namespace is not null or sel_concept_local is not null)
