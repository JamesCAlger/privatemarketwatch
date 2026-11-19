-- Baseline (spec section 8, D1): position rows this layer has and production does not, on either basis (published,
-- or a JV's own schedule). Each carries a cause in cmp_row_set; docs/baseline_roles_2026-11-19.md explains them.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['cmp_row_set_new_only']) }}
select basis, cik, report_date, accession, context_id, role_rule, reason, cause, cause_detail
from {{ ref('cmp_row_set') }}
where side = 'new_only'
