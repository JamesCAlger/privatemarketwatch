-- Slice 3 Task 3: the printed row (all cells) of the amount facts on one context, and the facts on it with units.
-- Variables: cik, rd (report date), ctx.
select r.accession, r.field, r.unit, r.value_filed, pl.row_index, pl.cell_index, dr.table_index, dr.row_in_table, dr.cells
from int_field_read r
left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
left join stg_filed_document_row dr on dr.accession = r.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
where r.cik = getvariable('cik') and cast(r.report_date as varchar) = getvariable('rd') and r.context_id = getvariable('ctx') and r.status = 'read'
limit 10
