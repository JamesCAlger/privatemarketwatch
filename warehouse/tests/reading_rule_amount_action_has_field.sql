-- Final fix wave F6: int_field_rule inner-joins fund rules to seeds/action_field.csv, so a rule whose action has no
-- action_field row would be dropped silently. Every loaded fund rule whose action is an amount action of slice 3 or a
-- rate action of slice 4 (seeds/reading_action.csv built_in_slice 3 or 4) must match at least one action_field row.
-- For the slice 3 actions its target must also be 'amount' or one of the fields action_field gives that action. The
-- slice 4 rate actions keep the loader's target (for example pik_rate for a PIK-only reading) while acting on the
-- fields action_field names (interest_rate, spread), so the target part is not checked for them. The concept_is_*
-- actions are left out: they choose which concept is read (int_field_read), not how a value is converted, and have no
-- action_field row by design.
with converting_rule as (
    select r.rule_id, r.cik, r.origin, r.action, r.target, a.built_in_slice
    from {{ ref('stg_reading_rule') }} r
    join {{ ref('reading_action') }} a on a.action = r.action
    where a.built_in_slice in ('3', '4') and r.action not like 'concept_is_%'
      -- owner ruling B (2026-11-23): a scale rule decides the scale of a read number (int_rate_scale), not which rule
      -- converts a field, so it has no action_field row by design
      and r.action <> 'ratio_value_is_percent'
)

select r.rule_id, r.cik, r.origin, r.action, r.target, 'action has no action_field row' as problem
from converting_rule r
anti join {{ ref('action_field') }} af on af.action = r.action
union all
select r.rule_id, r.cik, r.origin, r.action, r.target, 'target is neither amount nor a field of the action'
from converting_rule r
where r.built_in_slice = '3'
  and r.target is distinct from 'amount'
  and not exists (select 1 from {{ ref('action_field') }} af where af.action = r.action and af.field = r.target)
