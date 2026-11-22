-- Slice 3 Task 4 fix round 1: the table a printed row sits in (variables acc, row), and that table's first four rows.
with t as (
    select table_index from stg_filed_document_row where accession = getvariable('acc') and row_index = getvariable('row')
)
select dr.row_index, dr.table_index, dr.row_in_table, left(cast(dr.cells as varchar), 300) as cells
from stg_filed_document_row dr join t on t.table_index = dr.table_index
where dr.accession = getvariable('acc') and (dr.row_in_table <= 3 or dr.row_index = getvariable('row'))
order by dr.row_index
limit 10
