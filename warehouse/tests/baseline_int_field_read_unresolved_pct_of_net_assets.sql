-- Baseline (spec section 7, D5): position rows whose pct_of_net_assets could not be decided (two different numbers, one number
-- in two units, or a fact with no number). The value is left empty. Ceiling int_field_read_unresolved_pct_of_net_assets.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_read_unresolved_pct_of_net_assets']) }}
select accession, context_id, cik, report_date, reason, fact_count, read_rule_id
from {{ ref('int_field_read') }}
where field = 'pct_of_net_assets' and status = 'unresolved'
