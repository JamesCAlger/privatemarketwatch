-- Final fix wave F6: every cash row (is_cash) by rule number, role and which named source flagged it.
select r.role_rule, r.role, s.is_cash_axis, r.cash_rule_id is not null as has_cash_rule, t.cash_pattern_id, count(*) as n
from int_source_row r
join int_role_structure s using (accession, context_id)
left join int_role_text t using (accession, context_id)
where r.is_cash
group by all
order by all
