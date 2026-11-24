-- Slice 5 Task 3 exploration: the wrapper fair values set on contexts with no fair-value fact (rule 3): the printed row
-- of the context (the rows its placed facts sit in), and the cell where fair-value facts of other rows of that table sit.
with zero as (
    select c.correction_id, c.cik, c.accession, c.context_id, c.value, c.reason, c.evidence, s.report_date
    from main.stg_correction c
    join main.int_source_row s on s.accession = c.accession and s.context_id = c.context_id
    where c.store = 'wrapper:untagged_values' and c.field = 'fair_value' and s.role = 'not_schedule' and s.role_rule = 3
)
, ctx_rows as (
    select z.correction_id, pl.row_index, count(*) as facts_placed, list(distinct pl.concept) as concepts
    from zero z
    join main.stg_filed_fact_placement pl on pl.accession = z.accession and pl.context_id = z.context_id
    where pl.row_index is not null
    group by 1, 2
)
, fv_cells as (
    select pl.accession, dr.table_index, pl.cell_index, count(*) as n
    from main.stg_filed_fact_placement pl
    join main.stg_filed_document_row dr on dr.accession = pl.accession and dr.row_index = pl.row_index
    where pl.concept like '%:InvestmentOwnedAtFairValue' and pl.row_index is not null
    group by all
)
select z.report_date, z.context_id, z.value, r.row_index, r.facts_placed, dr.table_index, dr.cell_count
    , (select string_agg(cast(f.cell_index as varchar) || ':' || f.n, ' ' order by f.n desc) from fv_cells f
        where f.accession = z.accession and f.table_index = dr.table_index) as fv_cell_index
    , array_to_string(dr.cells, ' | ') as cells, z.reason
from zero z
left join ctx_rows r on r.correction_id = z.correction_id
left join main.stg_filed_document_row dr on dr.accession = z.accession and dr.row_index = r.row_index
order by 1, 2
