-- Text slice R phase 2 baseline (2026-11-26): agent proposals some check contradicts (int_text_proposal_verdict verdict
-- contradicted), against a ceiling set to the measured count (baseline_max.int_text_proposal_contradicted). Measured
-- 2026-11-26: 3. Two code mappings to SOFR, each in one column unit, where the base-level check finds 11% and 10% of the
-- tested rows outside the SOFR window, all in the 2022 quarters (term SOFR ran above overnight SOFR while rates rose:
-- a limit of the series, not shown to be a wrong mapping); one "S+#, #% Floor" shape whose floor test fails on all 5
-- rows that carry an all-in tag (the tag holds the spread or the floor). Listed in
-- docs/baseline_text_rates_phase2_2026-11-26.md section 6.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_proposal_contradicted']) }}
select proposal_kind, unit_key, shape, code, proposal, checks_contradicting
from {{ ref('int_text_proposal_verdict') }}
where verdict = 'contradicted'
