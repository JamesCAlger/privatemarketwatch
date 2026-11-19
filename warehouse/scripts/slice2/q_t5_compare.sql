-- Task 5: roles and the row-set comparison before the move (out/t5_*_before.parquet, built with seeds/filer_concept.csv
-- and loader version 1) against now. Rule ids are compared through their content, since every rule_id changes with
-- the loader's column list (version 2): an old wrapper rule id maps to the new id of the rule with the same cik,
-- origin, action, parameter and selectors; an old filer_concept_id maps to the new concept rule of the same cik and
-- the same reading (fair_value / term_fact). Lists every difference by kind; a clean move returns only 'rows' lines.
with b as (select * from read_parquet('scripts/slice2/out/t5_roles_before.parquet'))
, a as (select r.*, cf.fair_value_source, cf.term_fact_source from int_source_row r join int_context_feature cf using (accession, context_id))
, old_rule as (select * from read_parquet('scripts/slice2/out/t5_reading_rule_before.parquet'))
, new_rule as (select * from stg_reading_rule)
, rule_map as (
    select o.rule_id as old_id, n.rule_id as new_id
    from old_rule o join new_rule n
      on n.cik = o.cik and n.origin = o.origin and n.action = o.action
     and coalesce(n.parameter, '') = coalesce(o.parameter, '')
     and coalesce(n.sel_accession, '') = coalesce(o.sel_accession, '') and coalesce(n.sel_axis, '') = coalesce(o.sel_axis, '')
     and coalesce(n.sel_member, '') = coalesce(o.sel_member, '') and coalesce(n.sel_label, '') = coalesce(o.sel_label, '')
     and coalesce(n.sel_feature, '') = coalesce(o.sel_feature, '')
     and n.valid_from_text = o.valid_from and n.valid_to_text = o.valid_to
)
, concept_map as (
    select distinct b.cik, b.filer_concept_id as old_id, n.rule_id as new_id
    from b join new_rule n on n.cik = b.cik
      and n.action = case when b.filer_concept_id like 'bo_commit_term_%' or b.filer_concept_id like 'ares_pct_%'
                          then 'concept_is_term_fact' else 'concept_is_fair_value' end
    where b.filer_concept_id is not null
)
, j as (
    select b.accession, b.context_id, b.cik
        , b.role as role_b, a.role as role_a, b.role_rule as rr_b, a.role_rule as rr_a
        , b.reason as reason_b, a.reason as reason_a, b.scope as scope_b, a.scope as scope_a
        , b.is_cash = a.is_cash and b.is_published = a.is_published
          and b.cross_check_agrees is not distinct from a.cross_check_agrees as flags_same
        , coalesce(m1.new_id, b.rule_id) is not distinct from a.rule_id as rule_same
        , coalesce(m2.new_id, b.cash_rule_id) is not distinct from a.cash_rule_id as cash_rule_same
        , cm.new_id is not distinct from a.concept_rule_id as concept_same
        , b.filer_concept_id, a.concept_rule_id
    from b
    full join a using (accession, context_id)
    left join rule_map m1 on m1.old_id = b.rule_id
    left join rule_map m2 on m2.old_id = b.cash_rule_id
    left join concept_map cm on cm.old_id = b.filer_concept_id and cm.cik = b.cik
)
select 'rows' as kind, (select count(*) from b)::varchar as before, (select count(*) from a)::varchar as after, null as n
union all select 'role_or_rule_number_differs', role_b || ' r' || rr_b, role_a || ' r' || rr_a, count(*) from j where role_b is distinct from role_a or rr_b is distinct from rr_a group by 1, 2, 3
union all select 'reason_differs', reason_b, reason_a, count(*) from j where reason_b is distinct from reason_a group by 1, 2, 3
union all select 'scope_differs', scope_b, scope_a, count(*) from j where scope_b is distinct from scope_a group by 1, 2, 3
union all select 'flags_differ', null, null, count(*) from j where not coalesce(flags_same, false) group by 1 having count(*) > 0
union all select 'rule_id_differs', null, null, count(*) from j where not rule_same group by 1 having count(*) > 0
union all select 'cash_rule_id_differs', null, null, count(*) from j where not cash_rule_same group by 1 having count(*) > 0
union all select 'concept_id_differs', filer_concept_id, concept_rule_id, count(*) from j where not concept_same group by 1, 2, 3
union all select 'concept_id_map', cik || ' ' || old_id, new_id, null from concept_map
order by 1, 2
