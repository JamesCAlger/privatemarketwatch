-- Text slice R fix round 1 baseline (2026-11-26): agent proposals some check fails on at least 2 rows AND at least half
-- of its compared rows (int_text_proposal_verdict verdict contradicted_small, kinds column, role and code), against a
-- ceiling set to the measured count (baseline_max.int_text_proposal_contradicted_small). Measured 2026-11-26: 9. Codes 2:
-- one filer's SOFR code in two columns, whose only 2 and 3 rows with an all-in tag carry the spread in that tag. Roles
-- 7: a spread printed as a fraction ("SR + 0.0725", read as 0.0725 percent; the tag is 7.25); the spread and floor of an
-- "S+#, #% Floor" shape whose 3 floor-identity rows have the all-in tag holding the floor; the cash and PIK parts of
-- "#% Cash plus #% PIK, #% Floor" (the all-in tag holds the cash part); the two PIK numbers of "S+# Cash plus #% PIK,
-- #% PIK". Listed in docs/baseline_text_rates_phase2_2026-11-26.md section 10. Phase 3 (2026-11-26): 5; the two
-- codes and the "S+#, #% Floor" spread and floor left with check fix 1a (docs/baseline_text_rates_phase3_2026-11-26.md).
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_proposal_contradicted_small']) }}
select proposal_kind, unit_key, shape, number_index, code, proposal, checks_contradicting_small
from {{ ref('int_text_proposal_verdict') }}
where verdict = 'contradicted_small' and proposal_kind <> 'shape'
