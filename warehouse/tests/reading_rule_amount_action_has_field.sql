-- Final fix wave F6: int_field_rule inner-joins fund rules to seeds/action_field.csv, so a rule whose action has no
-- action_field row would be dropped silently. Every loaded fund rule whose action is an amount action of slice 3
-- (seeds/reading_action.csv built_in_slice 3) must match at least one action_field row, and its target must be
-- 'amount' or one of the fields action_field gives that action. The concept_is_* actions are left out: they choose
-- which concept is read (int_field_read), not how an amount is converted, and have no action_field row by design.
with amount_rule as (
    select r.rule_id, r.cik, r.origin, r.action, r.target
    from {{ ref('stg_reading_rule') }} r
    join {{ ref('reading_action') }} a on a.action = r.action
    where a.built_in_slice = '3' and r.action not like 'concept_is_%'
)

select r.rule_id, r.cik, r.origin, r.action, r.target, 'action has no action_field row' as problem
from amount_rule r
anti join {{ ref('action_field') }} af on af.action = r.action
union all
select r.rule_id, r.cik, r.origin, r.action, r.target, 'target is neither amount nor a field of the action'
from amount_rule r
where r.target is distinct from 'amount'
  and not exists (select 1 from {{ ref('action_field') }} af where af.action = r.action and af.field = r.target)
