-- Text slice P1 baseline (2026-11-26): published positions whose fair-value fact is placed visibly in two or more
-- printed rows (no row is taken), against a ceiling set to the measured count
-- (baseline_max.int_page_position_several_rows). Measured 2026-11-26: 0. The P0 query's one case (one fund, several
-- visible rows) counted every fair-value fact of the context by concept name; the fact int_field_read reads is in one row.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_page_position_several_rows']) }}
select * from {{ ref('int_page_position') }}
where is_published and placement_status = 'several_rows'
