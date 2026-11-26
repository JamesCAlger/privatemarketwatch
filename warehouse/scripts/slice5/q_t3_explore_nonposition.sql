-- Slice 5 Task 3 exploration: context-keyed corrections whose context is not a position here, by field and step.
select c.cik, c.store, c.kind, c.field, coalesce(cf2.step, 'NA') as step, s.role, s.role_rule, s.held_for_two_scopes
    , cf.has_term_fact, cf.fair_value_fact_count, s.report_date, count(*) as n
    , count(distinct c.context_id) as contexts, min(c.value) as min_value, max(c.value) as max_value
from main.stg_correction c
join main.int_source_row s on s.accession = c.accession and s.context_id = c.context_id
join main.int_context_feature cf on cf.accession = c.accession and cf.context_id = c.context_id
left join main.correction_field cf2 on cf2.correction_field = c.field
    and regexp_full_match(c.store, cf2.store_pattern)
where s.role <> 'position'
group by all
order by 1, 2, 3, 4, 11
