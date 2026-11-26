-- Slice 5 Task 3 exploration: the same 44 contexts, with cells placed on the table grid by their colspans. The fair-value
-- column is the grid column where the table's fair-value facts are placed (the commonest); the printed fair-value cell of
-- the context's row is the cell that covers that grid column.
with zero as (
    select c.correction_id, c.cik, c.accession, c.context_id, c.value, s.report_date
    from main.stg_correction c
    join main.int_source_row s on s.accession = c.accession and s.context_id = c.context_id
    where c.store = 'wrapper:untagged_values' and c.field = 'fair_value' and s.role = 'not_schedule' and s.role_rule = 3
)
, ctx_row as (
    select distinct z.correction_id, z.accession, pl.row_index
    from zero z
    join main.stg_filed_fact_placement pl on pl.accession = z.accession and pl.context_id = z.context_id
    where pl.row_index is not null
)
, grid as (
    select dr.accession, dr.row_index, dr.table_index, i - 1 as cell_index, dr.cells[i] as cell
        , coalesce(sum(coalesce(dr.cell_colspans[i], 1)) over (partition by dr.accession, dr.row_index order by i
            rows between unbounded preceding and 1 preceding), 0) as col_start
        , coalesce(dr.cell_colspans[i], 1) as span
    from main.stg_filed_document_row dr
    , range(1, dr.cell_count + 1) t(i)
    where dr.accession in (select accession from zero)
)
, fv_col as (
    select g.accession, g.table_index, g.col_start, count(*) as n
    from main.stg_filed_fact_placement pl
    join grid g on g.accession = pl.accession and g.row_index = pl.row_index and g.cell_index = pl.cell_index
    where pl.concept like '%:InvestmentOwnedAtFairValue'
    group by g.accession, g.table_index, g.col_start
    qualify row_number() over (partition by g.accession, g.table_index order by count(*) desc, g.col_start) = 1
)
select z.report_date, z.context_id, r.row_index, f.col_start as fv_col, f.n, g.cell as fv_cell
    , (select count(distinct r2.row_index) from ctx_row r2 where r2.correction_id = z.correction_id) as rows_of_context
from zero z
left join ctx_row r on r.correction_id = z.correction_id
left join main.stg_filed_document_row dr on dr.accession = r.accession and dr.row_index = r.row_index
left join fv_col f on f.accession = z.accession and f.table_index = dr.table_index
left join grid g on g.accession = z.accession and g.row_index = r.row_index
    and f.col_start >= g.col_start and f.col_start < g.col_start + g.span
order by 1, 2
