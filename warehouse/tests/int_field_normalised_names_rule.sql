-- Spec section 7: every normalised value names the rule it was read under, a fund rule (stg_reading_rule) or a global
-- default (seeds/field_rule_default.csv), and that rule's action is in the closed list (seeds/reading_action.csv) and
-- built in slice 3. A row that is not normalised carries no value and no rate.
select n.accession, n.context_id, n.field, n.rule_id, n.action, 'normalised without a known rule or built action' as problem
from {{ ref('int_field_normalised') }} n
left join {{ ref('reading_action') }} a on a.action = n.action
where n.status = 'normalised'
  and (n.rule_id is null or a.action is null or a.built_in_slice <> '3'
       or (n.rule_id not in (select rule_id from {{ ref('stg_reading_rule') }})
           and n.rule_id not in (select rule_id from {{ ref('field_rule_default') }})))
union all
select n.accession, n.context_id, n.field, n.rule_id, n.action, 'value on a row that is not normalised'
from {{ ref('int_field_normalised') }} n
where n.status <> 'normalised' and (n.value is not null or n.fx_rate is not null)
