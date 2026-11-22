-- Slice 3 Task 3: printed rows just before one table start (the schedule's title and unit statement). Variables: acc, tbl.
with t as (select min(row_index) r0 from stg_filed_document_row where accession = getvariable('acc') and table_index = getvariable('tbl'))
select row_index, table_index, cells from stg_filed_document_row, t
where accession = getvariable('acc') and row_index between t.r0 - 4 and t.r0 - 1
order by row_index limit 6
