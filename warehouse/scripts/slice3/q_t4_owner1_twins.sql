-- Slice 3 Task 4, owner item 1: for each position of one fund (variable cik) that carries a fact of one concept
-- (variable concept), every other position in the same filing with the same fair value, and the printed row of that
-- twin's fair value. Shows whether the commitment line's fair value is printed again on a schedule row.
with c as (
    select s.accession, s.context_id, s.report_date, cf.fair_value
    from stg_filed_fact f
    join int_source_row s on s.accession = f.accession and s.context_id = f.context_id
    join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.cik = getvariable('cik') and s.role = 'position' and f.concept_local = getvariable('concept')
)
, pos as (
    select s.accession, s.context_id, s.is_published, cf.fair_value
    from int_source_row s
    join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.cik = getvariable('cik') and s.role = 'position'
)
select c.report_date, c.context_id as commitment_context, c.fair_value, t.context_id as twin_context
    , t.is_published as twin_published
    , left(cast(dr.cells as varchar), 200) as twin_printed_row
from c
left join pos t on t.accession = c.accession and t.context_id <> c.context_id and t.fair_value = c.fair_value
left join int_field_read r on r.accession = t.accession and r.context_id = t.context_id and r.field = 'fair_value'
left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
left join stg_filed_document_row dr on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
where c.fair_value <> 0
order by c.report_date, c.context_id
limit 80
