-- Slice 3 Task 1, "nothing moves": the counts compared before and after. Run through slice2/run_sql.py; the output is
-- saved as out/counts_before.txt and out/counts_after.txt and diffed. One result set, ordered, so a text diff works.
select 'role' as what, cik, role as k1, cast(role_rule as varchar) as k2, '' as k3, '' as k4, count(*) as n
from int_source_row group by all
union all
select 'role_rule_id', cik, role, cast(role_rule as varchar), coalesce(rule_id, ''), '', count(*)
from int_source_row group by all
union all
select 'is_cash', cik, cast(is_cash as varchar), cast(is_published as varchar), '', '', count(*)
from int_source_row where is_cash group by all
union all
select 'cmp', cik, basis, side, coalesce(cause, ''), coalesce(cause_detail, ''), count(*)
from cmp_row_set group by all
union all
select 'cmp_role', cik, basis, side, role, cast(role_rule as varchar), count(*)
from cmp_row_set group by all
union all
select 'filing_candidate', cik, cast(report_date as varchar), accession, cast(position_fact_count as varchar), '', 1
from int_filing_candidate
union all
select 'subtotal', '', cast(is_subtotal as varchar), coalesce(near_miss_reason, ''), coalesce(subtotal_rule_id, ''), '', count(*)
from int_role_subtotal group by all
order by 1, 2, 3, 4, 5, 6
