-- Slice 3 Task 4: the printed rows of one table (variables acc, tbl) from row r0 to r1, and the text rows just above it
-- (row_index within 6 of the table's first row), to read its headings.
with t as (
    select min(row_index) as first_row from stg_filed_document_row
    where accession = getvariable('acc') and table_index = getvariable('tbl')
)
select dr.row_index, dr.table_index, dr.row_in_table, left(cast(dr.cells as varchar), 300) as cells
from stg_filed_document_row dr, t
where dr.accession = getvariable('acc')
  and ((dr.table_index = getvariable('tbl') and dr.row_in_table between getvariable('r0') and getvariable('r1'))
       or dr.row_index between t.first_row - 6 and t.first_row - 1)
order by dr.row_index
limit 60
