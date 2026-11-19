-- Final fix wave F2: the cash convention rows, with the source of their cash flag (rule 8 axis, a fund cash rule, a
-- seed cash pattern).
select x.basis, x.cik, x.report_date, r.role_rule, r.cash_rule_id, t.cash_pattern_id, count(*) as n
from cmp_row_set x
join int_source_row r using (accession, context_id)
left join int_role_text t using (accession, context_id)
where x.cause = 'convention'
group by all
order by all
