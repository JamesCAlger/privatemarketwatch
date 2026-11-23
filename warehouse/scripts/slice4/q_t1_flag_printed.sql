-- Slice 4 Task 1: for each flagged commitment line at one report date (variable rd, text), the printed row of its fair
-- value fact and of its twin's fair value fact (table index, row in table, cells). Read-only.
with f as (
    select r.accession, r.context_id, r.twin_context_id, r.report_date
    from int_repeated_commitment_value r
    where r.is_repeated_commitment_value and cast(r.report_date as varchar) = getvariable('rd')
)
, printed as (
    select rd.accession, rd.context_id, dr.table_index, dr.row_in_table, left(cast(dr.cells as varchar), 220) as cells
    from int_field_read rd
    join stg_filed_fact_placement pl on pl.accession = rd.accession and pl.fact_id = rd.fact_id
    join stg_filed_document_row dr on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
    where rd.field = 'fair_value'
)
select f.report_date, f.context_id, pl.table_index as line_table, pl.row_in_table as line_row, pl.cells as line_printed
    , f.twin_context_id, pt.table_index as twin_table, pt.row_in_table as twin_row, pt.cells as twin_printed
from f
left join printed pl on pl.accession = f.accession and pl.context_id = f.context_id
left join printed pt on pt.accession = f.accession and pt.context_id = f.twin_context_id
order by f.context_id
