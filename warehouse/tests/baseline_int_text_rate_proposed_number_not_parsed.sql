-- Text slice R phase 2 baseline (2026-11-26): rows of the proposed rate read whose k-th number does not parse as a
-- number (int_text_rate_proposed status number_not_parsed), against a ceiling set to the measured count
-- (baseline_max.int_text_rate_proposed_number_not_parsed). Measured 2026-11-26: 0. The number pattern of macro
-- text_numbers is the one macro text_shape masks, so a shape's k-th '#' is always a number; a row here means the two
-- patterns have drifted apart.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_rate_proposed_number_not_parsed']) }}
select accession, context_id, unit_key, number_index, cell_text
from {{ ref('int_text_rate_proposed') }}
where status = 'number_not_parsed'
