-- Text slice R phase 2 baseline (2026-11-26): leg identity rows that fail (int_text_check_leg_arithmetic verdict fail),
-- against a ceiling set to the measured count (baseline_max.int_text_leg_identity_fail). Measured 2026-11-26: 18 rows:
-- a_cash_plus_pik 4 (3 printed "Cash plus PIK" pairs whose all-in tag equals the cash part; 1 coupon printed as all
-- PIK whose tags carry no PIK, so the tagged cash leg is the whole coupon), b_pik_le_all_in 1 (a PIK tag above the
-- printed coupon), c_cash_le_all_in 3 (a printed coupon below the tagged one), d_floor_spread 8 (an all-in tag holding
-- the spread or the floor), f_printed_agree 2 (one cell printing two PIK rates). Listed in
-- docs/baseline_text_rates_phase2_2026-11-26.md section 3.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_leg_identity_fail']) }}
select accession, context_id, identity, lhs, rhs, detail, sources
from {{ ref('int_text_check_leg_arithmetic') }}
where verdict = 'fail'
