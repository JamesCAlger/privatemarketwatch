-- int_field_rule records tie_break_losers for the five read fields only; for principal_amount_usd it writes 0. That is
-- true while no rule for principal_amount_usd names a filing. Fails if one does, so the count is added before it lies.
select r.rule_id, r.cik, r.action, r.sel_accession
from {{ ref('stg_reading_rule') }} r
join {{ ref('action_field') }} af on af.action = r.action
where af.field = 'principal_amount_usd' and r.sel_accession is not null
