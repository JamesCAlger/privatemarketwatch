-- Text slice P3 baseline (fix round 1, 2026-11-26): placed facts read as a field (macro page_field_fact, any row role)
-- whose cell is given no column because its row's width is not the table's (column_rule none_row_width_differs) or it
-- starts left of the first leaf. Such a value is not put under a wrong header; it is counted here instead, against a
-- ceiling set to the measured count (baseline_max.int_page_field_fact_no_column). Measured 2026-11-26: see the ceiling;
-- all are on total rows of one fund's two-line-header tables (one filing, tables 22 to 27), whose cells are laid out
-- unlike the position rows.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_page_field_fact_no_column']) }}
with f as ({{ page_field_fact() }})
select accession, table_index, row_index, cell_index, field, column_rule
from f
where column_rule in ('none_row_width_differs', 'none_left_of_first_leaf')
