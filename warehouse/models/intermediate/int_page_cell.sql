-- Decides the true column of every non-empty cell of every row of the schedule tables (int_page_table) (text slice
-- P2, 2026-11-26). One row per (accession, row_index, cell_index); cell_index is 0-based, as in
-- stg_filed_fact_placement.
--
-- text: the cell through macro page_text (white space runs, the no-break space too, become one space; ends trimmed).
-- Cells whose text is '' are not kept, but they still take their columns.
-- Columns are 0-based. A cell's naive start is the sum of the colspans of the cells before it in its row (a missing or
-- non-positive colspan counts 1); col_end = col_start + colspan - 1.
-- Rowspan rule: a cell with rowspan above 1 also covers its columns in the next rowspan - 1 rows of the table. span_rule:
--   none                 no cell above covers this row: naive starts are the true columns.
--   span_from_row_above  every covering cell sits in the row immediately above, and that row is itself not covered.
--                        The row's cells are laid, in order, into the columns the covering cells leave free: a cell
--                        whose naive start is k starts at the k-th free column (0-based) and ends at the free column
--                        k + colspan - 1. Example (a two-line header): line 1 "Company" (cols 0-2, rowspan 2),
--                        "Investment" (3-5, rowspan 2), "" (6-8), "Interest" (9-17); line 2 cells "", "Ref. Rate",
--                        "Cash" of colspan 3 land at 6, 9 and 12, not 0, 3 and 6.
--   deeper_span          a covering cell sits two or more rows above, or the row above is itself covered. Not
--                        resolved: the naive starts are kept and the row is flagged, not guessed.
-- row_width_ok: the row's width (its colspans plus the columns covering cells take in it) equals the table's width.
with schedule as (
    select accession, table_index, width
    from {{ ref('int_page_table') }}
)

, cell as (
    select
        dr.accession
        , dr.table_index
        , dr.row_index
        , dr.row_in_table
        , dr.fact_count as row_fact_count
        , i - 1 as cell_index
        , {{ page_text('dr.cells[i]') }} as text
        , greatest(coalesce(dr.cell_colspans[i], 1), 1) as colspan
        , greatest(coalesce(dr.cell_rowspans[i], 1), 1) as rowspan
        , coalesce(sum(greatest(coalesce(dr.cell_colspans[i], 1), 1)) over (
            partition by dr.accession, dr.row_index order by i rows between unbounded preceding and 1 preceding), 0)
            as naive_start
    from {{ ref('stg_filed_document_row') }} dr
    join schedule s on s.accession = dr.accession and s.table_index = dr.table_index
    , range(1, dr.cell_count + 1) t(i)
)

, table_row as (
    select accession, table_index, row_index, row_in_table, sum(colspan) as naive_width
    from cell
    group by 1, 2, 3, 4
)

, cover as (
    -- each row a rowspan cell covers below its own row, with the columns it covers there
    select
        r.accession
        , r.table_index
        , r.row_index
        , r.row_in_table
        , r.row_in_table - c.row_in_table as distance
        , c.row_in_table as source_row_in_table
        , c.naive_start as cover_start
        , c.naive_start + c.colspan - 1 as cover_end
    from cell c
    join table_row r
        on r.accession = c.accession and r.table_index = c.table_index
        and r.row_in_table > c.row_in_table and r.row_in_table < c.row_in_table + c.rowspan
    where c.rowspan > 1
)

, covered_row as (
    select distinct accession, table_index, row_in_table from cover
)

, row_span as (
    select
        c.accession
        , c.row_index
        , case
            when max(c.distance) > 1 or bool_or(cr.row_in_table is not null) then 'deeper_span'
            else 'span_from_row_above'
        end as span_rule
        , sum(c.cover_end - c.cover_start + 1) as covered_width
    from cover c
    left join covered_row cr
        on cr.accession = c.accession and cr.table_index = c.table_index and cr.row_in_table = c.source_row_in_table
    group by 1, 2
)

, free_column as (
    -- the columns a span_from_row_above row leaves free, numbered 0, 1, ... from the left
    select
        rs.accession
        , rs.row_index
        , t.col
        , row_number() over (partition by rs.accession, rs.row_index order by t.col) - 1 as k
    from row_span rs
    join table_row r on r.accession = rs.accession and r.row_index = rs.row_index
    , range(0, cast(r.naive_width + rs.covered_width as bigint)) t(col)
    where rs.span_rule = 'span_from_row_above'
        and not exists (
            select 1 from cover c
            where c.accession = rs.accession and c.row_index = rs.row_index and t.col between c.cover_start and c.cover_end
        )
)

select
    c.accession
    , c.table_index
    , c.row_index
    , c.row_in_table
    , c.cell_index
    , coalesce(fs.col, c.naive_start) as col_start
    , coalesce(fe.col, c.naive_start + c.colspan - 1) as col_end
    , c.text
    , c.row_fact_count
    , coalesce(rs.span_rule, 'none') as span_rule
    , r.naive_width + coalesce(rs.covered_width, 0) = s.width as row_width_ok
from cell c
join schedule s on s.accession = c.accession and s.table_index = c.table_index
join table_row r on r.accession = c.accession and r.row_index = c.row_index
left join row_span rs on rs.accession = c.accession and rs.row_index = c.row_index
left join free_column fs
    on rs.span_rule = 'span_from_row_above' and fs.accession = c.accession and fs.row_index = c.row_index
    and fs.k = c.naive_start
left join free_column fe
    on rs.span_rule = 'span_from_row_above' and fe.accession = c.accession and fe.row_index = c.row_index
    and fe.k = c.naive_start + c.colspan - 1
where c.text <> ''
