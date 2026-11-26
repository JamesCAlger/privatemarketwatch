-- Decides the column unit of every data cell of the schedule tables that have a header (text slice P3,
-- 2026-11-26). One row per non-empty cell (int_page_cell) in a row below the table's last header line
-- (int_page_table.header_last_row_in_table): (accession, row_index, cell_index).
--
-- The cell's column is the leaf of int_page_column whose zone (col_start to zone_end) contains the cell's col_start.
-- Example: under a header "Par Amount/Units" at columns 39-44, a "$" cell at column 39 and its number at column 40
-- both get that header. A cell that starts left of the first leaf gets none: column_col_start, column_index and
-- header_signature are null. Cells of tables without a header (header_status none or ambiguous) have no row here.
-- shape: macro page_cell_shape of the cell's text (empty_marker, footnote_mark, date, percent, number, text).
with header_table as (
    select accession, table_index, header_last_row_in_table
    from {{ ref('int_page_table') }}
    where header_status in ('one_line', 'two_lines')
)

select
    c.accession
    , c.row_index
    , c.cell_index
    , c.table_index
    , c.row_in_table
    , c.col_start
    , c.text
    , {{ page_cell_shape('c.text') }} as shape
    , c.row_fact_count
    , col.col_start as column_col_start
    , col.column_index
    , col.header_signature
from {{ ref('int_page_cell') }} c
join header_table h
    on h.accession = c.accession and h.table_index = c.table_index and c.row_in_table > h.header_last_row_in_table
left join {{ ref('int_page_column') }} col
    on col.accession = c.accession and col.table_index = c.table_index
    and c.col_start between col.col_start and col.zone_end
