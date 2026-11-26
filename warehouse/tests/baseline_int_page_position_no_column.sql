-- Text slice P3 baseline (2026-11-26): published positions with a printed row none of whose cells is under a column of
-- int_page_column (the table has no header, or every cell starts left of the first leaf), against a ceiling set to the
-- measured count (baseline_max.int_page_position_no_column). Measured 2026-11-26: see the ceiling; these are the
-- positions of the table in baseline_int_page_table_no_header.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_page_position_no_column']) }}
select p.accession, p.context_id, p.row_index
from {{ ref('int_page_position') }} p
where p.is_published and p.placement_status = 'one_row'
    and not exists (
        select 1 from {{ ref('int_page_cell_column') }} c
        where c.accession = p.accession and c.row_index = p.row_index and c.column_col_start is not null
    )
