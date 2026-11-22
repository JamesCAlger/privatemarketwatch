-- Slice 3 Task 4 (exploration): every filed fact on one context (variables acc, ctx), with its printed row.
select f.concept_namespace, f.concept_local, f.unit_id, f.value_numeric, f.is_nil, pl.row_index, pl.cell_index
    , left(cast(dr.cells as varchar), 400) as cells
from stg_filed_fact f
left join stg_filed_fact_placement pl on pl.accession = f.accession and pl.fact_id = f.fact_id
left join stg_filed_document_row dr on dr.accession = f.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
where f.accession = getvariable('acc') and f.context_id = getvariable('ctx')
order by f.concept_local
limit 40
