-- Slice 3 Task 4, owner item 2: the printed rows around one rollup (variables acc, ctx): from 2 rows above its fair
-- value's row to 8 below, each with the contexts and concepts placed on it and the context's role.
with anchor as (
    select min(coalesce(pl.row_index, pl.shown_row_index)) as r
    from stg_filed_fact_placement pl
    where pl.accession = getvariable('acc') and pl.context_id = getvariable('ctx')
)
, placed as (
    select coalesce(pl.row_index, pl.shown_row_index) as row_index
        , string_agg(distinct pl.context_id || ':' || s.role, ' ') as contexts
        , string_agg(f.concept_local || '=' || cast(f.value_numeric as varchar), ' ' order by f.concept_local) as facts
    from stg_filed_fact_placement pl
    join stg_filed_fact f on f.accession = pl.accession and f.fact_id = pl.fact_id
    left join int_source_row s on s.accession = pl.accession and s.context_id = pl.context_id
    where pl.accession = getvariable('acc')
    group by 1
)
select dr.row_index, left(cast(dr.cells as varchar), 230) as cells, left(p.contexts, 120) as contexts
    , left(p.facts, 260) as facts
from stg_filed_document_row dr cross join anchor a
left join placed p on p.row_index = dr.row_index
where dr.accession = getvariable('acc') and dr.row_index between a.r - 2 and a.r + 8
order by dr.row_index
limit 20
