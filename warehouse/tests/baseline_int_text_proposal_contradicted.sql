-- Text slice R phase 2 baseline (2026-11-26; per number role since fix round 1): agent proposals some check contradicts
-- (int_text_proposal_verdict verdict contradicted, kinds column, role and code; the shape rows only summarise their
-- roles and are not counted), against a ceiling set to the measured count (baseline_max.int_text_proposal_contradicted).
-- Measured 2026-11-26 after fix round 1: 6. Codes 4: two SOFR mappings failed by the base-level check in the 2022
-- quarters (term SOFR above overnight SOFR; the legend agrees), and two code mappings answered with the latest legend
-- name where earlier filings define the code otherwise (one filer's B: BBSW until 2024-09-30, BBSY from 2025; its C:
-- CDOR until 2025-03-31, CORRA from 2026): dated rules, not one name. Roles 2: the spread and floor of one
-- "S+#, #% Floor" shape, failed by the floor identity on 5 rows whose all-in tag holds the spread or the floor.
-- Listed in docs/baseline_text_rates_phase2_2026-11-26.md section 10.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_proposal_contradicted']) }}
select proposal_kind, unit_key, shape, number_index, code, proposal, checks_contradicting
from {{ ref('int_text_proposal_verdict') }}
where verdict = 'contradicted' and proposal_kind <> 'shape'
