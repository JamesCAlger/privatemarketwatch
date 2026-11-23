-- Slice 4 Task 3: counts for the ceilings. One row per check and field.
select 'rate_conflict_positions' as check_name, '' as field, count(distinct accession || '|' || context_id) as n
from int_field_rule where resolution = 'rule_conflict' and field in ('interest_rate', 'pik_rate', 'spread', 'maturity_date')
union all
select 'bound_0_40', field, count(*) from int_field_normalised
where field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread') and status = 'normalised' and (value < 0 or value > 40)
group by field
union all
select 'maturity_before_report_date', field, count(*) from int_field_normalised
where field = 'maturity_date' and status = 'normalised' and value_date < report_date group by field
union all
select 'legs_check_rows', '', count(*) from int_rate_legs_check
union all
select 'filed_pure_between_0.5_and_1 (production keeps as percent)', r.field, count(*) from int_field_read r
where r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread') and r.status = 'read'
  and r.unit in ('pure', 'utr:Rate') and r.value_filed > 0.5 and r.value_filed <= 1 group by r.field
union all
select 'filed_pure_above_1', r.field, count(*) from int_field_read r
where r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread') and r.status = 'read'
  and r.unit in ('pure', 'utr:Rate') and r.value_filed > 1 group by r.field
order by 1, 2
