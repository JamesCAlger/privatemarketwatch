-- Fund rules of the amount actions (seeds/action_field.csv) may select only on what int_field_rule reads: the fund, an
-- accession, dates, and for par_tagged_as_units a row mode it knows (sel_feature equal to the parameter). A selector
-- the model does not read would be ignored, and the rule would apply more widely than written.
select r.rule_id, r.cik, r.action, r.parameter, 'selector not read by int_field_rule' as problem
from {{ ref('stg_reading_rule') }} r
where r.action in (select action from {{ ref('action_field') }})
  and (r.cik is null or r.sel_axis is not null or r.sel_member is not null or r.sel_label is not null
       or r.sel_label_pattern is not null or r.sel_concept_namespace is not null or r.sel_concept_local is not null
       or (r.sel_feature is not null and r.action <> 'par_tagged_as_units'))
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
