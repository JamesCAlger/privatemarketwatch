-- Final fix wave F6: seeds/action_field.csv has one row per (action, field). A repeated pair would match a rule to a
-- field twice in int_field_rule and could pass as two candidates of one rule.
select action, field, count(*) as n
from {{ ref('action_field') }}
group by 1, 2
having count(*) > 1
