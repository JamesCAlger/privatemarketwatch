-- Slice 4 Task 3: rows each loaded rate rule decides (or ties on), per fund, rule action, field, resolution and quarter.
select u.cik, r.action, u.field, u.resolution, string_agg(cast(u.report_date as varchar) || ':' || cast(n as varchar), ', ' order by u.report_date) as per_quarter, sum(n) as total
from (
    select cik, field, resolution, report_date, coalesce(rule_id, '') as rule_id, count(*) as n
    from int_field_rule where field in ('interest_rate', 'spread') and resolution in ('rule', 'rule_conflict', 'feature_missing')
    group by all
) u
left join stg_reading_rule r on r.rule_id = u.rule_id
where u.resolution <> 'rule' or r.rule_id is not null
group by all
order by 1, 2, 3, 4
