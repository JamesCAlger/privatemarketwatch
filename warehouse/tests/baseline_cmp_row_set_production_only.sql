-- Baseline (spec section 8, D1): production position rows this layer does not publish as positions on the same basis.
-- Each carries a cause in cmp_row_set; docs/baseline_roles_2026-11-19.md explains them.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['cmp_row_set_production_only']) }}
select basis, cik, report_date, accession, context_id, role, role_rule, reason, accounting_record_class, fair_value, cause, cause_detail
from {{ ref('cmp_row_set') }}
where side = 'production_only'
