-- Final fix wave F4: position rows whose cost int_field_read reads under a fund rule concept_is_cost and where it
-- differs from int_context_feature.cost (the standard concept only, which the subtotal rule reads). Measured
-- 2026-11-22: 196 rows, every row read under such a rule (the standard cost is absent on each). Measured, not built:
-- giving int_role_subtotal the filer cost on these rows changes no subtotal decision and no near-miss reason
-- (scripts/slice3/q_fw_f4_subtotal_with_filer_cost.sql: 0 rows; all 196 sit in rule 6's pool). A rise means a new
-- filer-concept cost the subtotal rule does not see. Ceiling int_field_read_cost_filer_concept.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_read_cost_filer_concept']) }}
select f.accession, f.context_id, f.cik, f.report_date, f.value_filed, cf.cost, f.read_rule_id
from {{ ref('int_field_read') }} f
join {{ ref('int_context_feature') }} cf on cf.accession = f.accession and cf.context_id = f.context_id
join {{ ref('stg_reading_rule') }} r on r.rule_id = f.read_rule_id and r.action = 'concept_is_cost'
where f.field = 'cost'
  and f.value_filed is distinct from cf.cost
