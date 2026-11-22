-- Slice 3 final fix wave: F3 tie-break and F4 cost counts (read-only).
select 'f3_tie_break' as check_name, field as k
    , count(*) filter (where tie_break_losers > 0) as n_tie_break
    , count(*) filter (where tie_break_same_effect = false) as n_different
from int_field_rule
group by 1, 2
union all
select 'f4_cost_rows_under_concept_is_cost', 'all', count(*)
    , count(*) filter (where r.value_filed is distinct from cf.cost)
from int_field_read r
join int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
join stg_reading_rule rr on rr.rule_id = r.read_rule_id and rr.action = 'concept_is_cost'
where r.field = 'cost'
union all
select 'f4_cost_differs_other_rows', 'all', count(*), count(*) filter (where r.status = 'read')
from int_field_read r
join int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
where r.field = 'cost' and r.value_filed is distinct from cf.cost
  and r.read_rule_id not in (select rule_id from stg_reading_rule where action = 'concept_is_cost')
union all
select 'f4_cost_differs_null_rule', coalesce(r.status, '-') || '/' || coalesce(cast(cf.cost is null as varchar), '-'), count(*), 0
from int_field_read r
join int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
where r.field = 'cost' and r.value_filed is distinct from cf.cost and r.read_rule_id is null
group by 1, 2
order by 1, 2
limit 50
