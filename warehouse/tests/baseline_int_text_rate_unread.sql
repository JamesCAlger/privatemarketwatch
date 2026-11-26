-- Text slice R phase 3 baseline (2026-11-26): printed rate cells in ruled columns that the accepted rules leave unread
-- (int_text_rate_read_cell status other than read and no_value), one row per fund, column unit, shape and status with
-- the positions and cells, against a ceiling on the number of such groups (baseline_max.int_text_rate_unread_groups).
-- Measured 2026-11-26: listed in docs/baseline_text_rates_phase3_2026-11-26.md section 4 (statuses no_role_rule,
-- code_no_rule, legend_two_rates, not_a_code; positions in the doc). A new unread shape adds a group and fails the build.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_rate_unread_groups']) }}
select cik, unit_key, shape, status, count(*) as cells, count(distinct accession || '|' || context_id) as positions
from {{ ref('int_text_rate_read_cell') }}
where status not in ('read', 'no_value')
group by all
