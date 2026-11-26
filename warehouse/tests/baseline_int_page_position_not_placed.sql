-- Text slice P1 baseline (2026-11-26): published positions whose fair-value fact (as int_field_read reads it) has no
-- visible placement in a printed row, against a ceiling set to the measured count
-- (baseline_max.int_page_position_not_placed). Measured 2026-11-26: 0 on the five funds. The P0 query of 2026-11-25
-- counted 2,270 of one fund's positions as unplaced: it matched the standard fair-value concept by name, and those
-- positions' fair value is read from the fund's own concept under a fund rule (2024-12-31 to 2026-09-30); all are placed.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_page_position_not_placed']) }}
select * from {{ ref('int_page_position') }}
where is_published and placement_status = 'not_placed'
