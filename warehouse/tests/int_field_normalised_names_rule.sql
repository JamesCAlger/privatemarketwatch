-- Spec section 7: every normalised value names the rule it was read under, a fund rule (stg_reading_rule) or a global
-- default (seeds/field_rule_default.csv), and that rule's action is in the closed list (seeds/reading_action.csv) and
-- built for the field (macro action_is_built). A row that is not normalised carries no value and no rate; a normalised
-- row carries a value unless its reason is moved_to_principal. maturity_date (slice 4 Task 3) carries its value in
-- value_date.
select n.accession, n.context_id, n.field, n.rule_id, n.action, 'normalised without a known rule or built action' as problem
from {{ ref('int_field_normalised') }} n
left join {{ ref('reading_action') }} a on a.action = n.action
where n.status = 'normalised'
  and (n.rule_id is null or a.action is null
       or not {{ action_is_built('a.built_in_slice', 'a.built_early_for_field', 'n.field') }}
       or (n.rule_id not in (select rule_id from {{ ref('stg_reading_rule') }})
           and n.rule_id not in (select rule_id from {{ ref('field_rule_default') }})))
union all
select n.accession, n.context_id, n.field, n.rule_id, n.action, 'value on a row that is not normalised'
from {{ ref('int_field_normalised') }} n
where n.status <> 'normalised' and (n.value is not null or n.fx_rate is not null or n.value_date is not null)
union all
-- final fix wave F8: a normalised row carries a value; the one documented exception is shares moved to the principal
-- (reason moved_to_principal), whose value is null on purpose. Slice 4 Task 1, item c: null-safe, so a null value
-- with a null reason fails (with "<>" it passed)
select n.accession, n.context_id, n.field, n.rule_id, n.action, 'normalised without a value'
from {{ ref('int_field_normalised') }} n
where n.status = 'normalised' and n.value is null and n.value_date is null
  and n.reason is distinct from 'moved_to_principal'
union all
select n.accession, n.context_id, n.field, n.rule_id, n.action, 'rate_kind on a row that is not interest_rate'
from {{ ref('int_field_normalised') }} n
where n.rate_kind is not null and n.field <> 'interest_rate'
