-- Text slice P3 baseline (2026-11-26): schedule tables with no header taken (header_status none or ambiguous), whose
-- cells get no column, against a ceiling set to the measured count (baseline_max.int_page_table_no_header). Measured
-- 2026-11-26: 1, a 28-row table of one fund (named in docs/baseline_page_structure_2026-11-26.md) whose first position row is its 18th
-- row and which has no row with 3 or more non-empty cells above it.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_page_table_no_header']) }}
select * from {{ ref('int_page_table') }}
where header_status in ('none', 'ambiguous')
