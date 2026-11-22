-- Slice 3 Task 4, owner item 1: position rows of one fund (variable cik) that carry a fact of one concept (variable
-- concept, the local name), at one report date (variable rd): the fact, the row's fair value as both sides hold it,
-- and the printed row of the concept's fact with the table's heading rows. Read-only.
with f as (
    select f.accession, f.context_id, f.fact_id, f.value_numeric as concept_value
    from stg_filed_fact f
    join int_source_row s on s.accession = f.accession and s.context_id = f.context_id
    where s.cik = getvariable('cik') and cast(s.report_date as varchar) = getvariable('rd') and s.role = 'position'
      and f.concept_local = getvariable('concept')
)
select f.context_id, f.concept_value, a.value_new as fv_new, a.value_production as fv_production, s.is_published
    , dr.table_index, dr.row_in_table
    , left(cast(dr.cells as varchar), 260) as printed_row
from f
join int_source_row s on s.accession = f.accession and s.context_id = f.context_id
left join cmp_amount a on a.accession = f.accession and a.context_id = f.context_id and a.field = 'fair_value'
left join stg_filed_fact_placement pl on pl.accession = f.accession and pl.fact_id = f.fact_id
left join stg_filed_document_row dr on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
order by dr.row_index
limit 40
