-- Fund rules of the actions int_field_rule reads (seeds/action_field.csv) may select only on what int_field_rule
-- reads: the fund, an accession, dates, for par_tagged_as_units a row mode it knows (sel_feature equal to the
-- parameter), and since slice 4 Task 3 a row feature that is the action's applies_to in action_field (pik_tag_only for
-- the PIK-only readings). A selector the model does not read would be ignored, and the rule would apply more widely
-- than written.
select r.rule_id, r.cik, r.action, r.parameter, 'selector not read by int_field_rule' as problem
from {{ ref('stg_reading_rule') }} r
where r.action in (select action from {{ ref('action_field') }})
  and (r.cik is null or r.sel_axis is not null or r.sel_member is not null or r.sel_label is not null
       or r.sel_label_pattern is not null or r.sel_concept_namespace is not null or r.sel_concept_local is not null
       or (r.sel_feature is not null and r.action <> 'par_tagged_as_units'
           and r.sel_feature not in (select af.applies_to from {{ ref('action_field') }} af where af.action = r.action)))
union all
select r.rule_id, r.cik, r.action, r.parameter, 'a feature rule whose feature is not on every field of its action'
from {{ ref('stg_reading_rule') }} r
join {{ ref('action_field') }} af on af.action = r.action
where r.sel_feature is not null and r.action <> 'par_tagged_as_units' and af.applies_to <> r.sel_feature
union all
select r.rule_id, r.cik, r.action, r.parameter, 'unknown par_tagged_as_units mode, or accession and mode do not agree'
from {{ ref('stg_reading_rule') }} r
where r.action = 'par_tagged_as_units'
  and not coalesce(
      (r.parameter = 'whole_filing' and r.sel_accession is not null and r.sel_feature is null)
      or (r.parameter in ('rows_near_cost', 'rated_rows_near_cost', 'rows_within_twice_cost',
                          'listed_rows_without_instrument')
          and r.sel_accession is null and r.sel_feature = r.parameter),
      false)
