-- Slice 3 Task 3: loaded rules whose action is built in slice 3 (or with a slice-3 target), all columns.
select r.cik, r.action, r.target, r.parameter, r.sel_accession, r.sel_axis, r.sel_member, r.sel_feature
    , r.sel_concept_namespace, r.sel_concept_local, r.valid_from, r.valid_to, r.origin, r.rule_class, r.priority, r.rule_id
from stg_reading_rule r
left join reading_action a on a.action = r.action
where a.built_in_slice = '3' or r.action like '%usd%' or r.origin like '%principal_usd%'
order by r.action, r.cik
limit 100
