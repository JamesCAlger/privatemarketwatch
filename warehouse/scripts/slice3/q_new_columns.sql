-- Slice 3 Task 1: the new columns. cash_source by value (with is_cash, role_rule); held_for_two_scopes; fair_value_rule_id
-- by fair_value_source kind; contexts with a fair-value fact but no rule (expected 0).
select 'cash_source' as what, coalesce(cash_source, '(null)') as k1, cast(is_cash as varchar) as k2, cast(role_rule as varchar) as k3, count(*) as n
from int_source_row group by all
union all
select 'held_for_two_scopes', cast(held_for_two_scopes as varchar), role, cast(role_rule as varchar), count(*) from int_source_row where held_for_two_scopes group by all
union all
select 'fair_value_rule_id', case when fair_value_source = 'standard' then 'standard' when fair_value_source is null then '(null)' else 'fund_rule' end
    , coalesce(fair_value_rule_id, '(null)'), cast(fair_value_fact_count > 0 as varchar), count(*)
from int_context_feature group by all
order by 1, 2, 3, 4
