-- Spec section 7: every normalised value names the rule it was read under, a fund rule (stg_reading_rule) or a global
-- default (seeds/field_rule_default.csv), and that rule's action is in the closed list (seeds/reading_action.csv) and
-- built for the field (built_in_slice 3, or built_early_for_field names the field). A row that is not normalised
-- carries no value and no rate; a normalised row carries a value unless its reason is moved_to_principal.
select n.accession, n.context_id, n.field, n.rule_id, n.action, 'normalised without a known rule or built action' as problem
from {{ ref('int_field_normalised') }} n
left join {{ ref('reading_action') }} a on a.action = n.action
where n.status = 'normalised'
  and (n.rule_id is null or a.action is null
       or not coalesce(a.built_in_slice = '3' or a.built_early_for_field = n.field, false)
       or (n.rule_id not in (select rule_id from {{ ref('stg_reading_rule') }})
           and n.rule_id not in (select rule_id from {{ ref('field_rule_default') }})))
union all
select n.accession, n.context_id, n.field, n.rule_id, n.action, 'value on a row that is not normalised'
from {{ ref('int_field_normalised') }} n
where n.status <> 'normalised' and (n.value is not null or n.fx_rate is not null)
union all
-- final fix wave F8: a normalised row carries a value; the one documented exception is shares moved to the principal
-- (reason moved_to_principal), whose value is null on purpose
select n.accession, n.context_id, n.field, n.rule_id, n.action, 'normalised without a value'
from {{ ref('int_field_normalised') }} n
where n.status = 'normalised' and n.value is null and n.reason <> 'moved_to_principal'
