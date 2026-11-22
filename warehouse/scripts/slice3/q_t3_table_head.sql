-- Slice 3 Task 3: the first rows of one printed table (header), to read its unit statement. Variables: acc, tbl.
select row_index, row_in_table, cells from stg_filed_document_row
where accession = getvariable('acc') and table_index = getvariable('tbl') and row_in_table < 4
order by row_in_table
limit 6
