-- Baseline (spec section 8): one-sided rows that no cause rule in cmp_row_set explains.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['cmp_row_set_not_yet_explained']) }}
select basis, side, cik, report_date, accession, context_id, role, role_rule, reason, fair_value, new_fair_value
from {{ ref('cmp_row_set') }}
where cause = 'not_yet_explained'
