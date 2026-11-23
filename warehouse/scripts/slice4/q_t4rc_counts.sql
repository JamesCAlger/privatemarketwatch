-- Slice 4 Task 4 ruling change (PIK-only readings): unresolved rate rows of int_field_normalised per field and
-- reason, and rate rule conflicts in int_field_rule (positions).
select 'normalised' as what, field, reason, count(*) as n
from int_field_normalised
where status = 'unresolved'
  and field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
group by all
union all
select 'rule_conflict_positions', null, null, count(distinct accession || '|' || context_id)
from int_field_rule
where resolution = 'rule_conflict' and field in ('interest_rate', 'pik_rate', 'spread', 'maturity_date')
union all
select 'feature_missing_rows', null, null, count(*) from int_field_rule where resolution = 'feature_missing'
order by 1, 2, 3
