-- Text slice P2 baseline (2026-11-26): rows of schedule tables (with at least one non-empty cell) whose width, after
-- the rowspan rule, differs from the table's modal width, against a ceiling set to the measured count
-- (baseline_max.int_page_cell_row_width). Measured 2026-11-26: 31 rows, all one fund's: 18 header rows of its
-- width-54 tables (the header's colspans sum to less than the data rows'), and 13 total rows ("Total controlled ...",
-- "Total non-controlled ...") and one section heading in its two-line-header tables, whose cells are laid out
-- differently from the position rows. The P0 count of 153 rows included rows with no text and the 115 second header
-- lines the rowspan rule now places.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_page_cell_row_width']) }}
select distinct accession, table_index, row_index
from {{ ref('int_page_cell') }}
where not row_width_ok
