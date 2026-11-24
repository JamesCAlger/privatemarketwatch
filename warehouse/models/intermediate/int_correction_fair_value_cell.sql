-- Decides, for each context a correction gives a fair value at step filed (a printed value with no tag, wrapper
-- untagged_values) where the context carries no fair-value fact, what its printed fair-value cell shows (owner answer
-- of 2026-11-24 on decision 4: such a fair value is applied only where the printed cell prints a dash or a zero; slice 5
-- Task 3). One row per such (accession, context_id).
--
-- The printed row: the one table row (stg_filed_document_row) in which the filed layer placed the context's facts
-- (fact_placement.row_index; a hidden fact's shown row is not used). None, or facts in two rows: printed_row_index null.
-- The fair-value column: cells are laid on the table's grid by their colspans (a cell starts at the sum of the colspans
-- before it, a missing colspan counts 1). The column is the grid column where the fair-value facts of the other rows of
-- the same table are placed (the fair-value concept of seed concept_map, by local name, any prefix), the commonest one;
-- a tie goes to the leftmost. fair_value_column null when the table places no fair-value fact.
-- printed_cell: the cell of the printed row that covers the fair-value column (null when either is missing).
-- prints_dash_or_zero, the exact test: the cell with white space (also the no-break space U+00A0), '$', '(', ')' and
-- ',' removed is a single dash ('-', the en dash U+2013 or the em dash U+2014), or a zero written with digits ('0',
-- '0.0', '0.00', ...). Anything else is false, a null cell too. Examples true: an em dash alone, ' - ', '$ ' then an
-- em dash, '0', '(0)', '$0.00'. Examples false: '1,576', '0.5', '10', 'N/A', '--', '' (an empty cell is not a printed
-- zero), a dash in another column of the row.
with target as (
    select distinct t.accession, t.context_id
    from {{ ref('int_correction_target') }} t
    join {{ ref('int_context_feature') }} cf on cf.accession = t.accession and cf.context_id = t.context_id
    where t.step = 'filed' and t.layer_field = 'fair_value' and cf.fair_value_fact_count = 0
)

, context_row as (
    select t.accession, t.context_id, min(pl.row_index) as row_index, count(distinct pl.row_index) as row_count
    from target t
    join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = t.accession and pl.context_id = t.context_id
    where pl.row_index is not null
    group by 1, 2
)

, printed_row as (
    select accession, context_id, row_index
    from context_row
    where row_count = 1
)

, printed_table as (
    select distinct p.accession, d.table_index
    from printed_row p
    join {{ ref('stg_filed_document_row') }} d on d.accession = p.accession and d.row_index = p.row_index
)

, grid as (
    -- every cell of the tables the printed rows sit in, with its first grid column and its width
    select
        dr.accession
        , dr.row_index
        , dr.table_index
        , i - 1 as cell_index
        , dr.cells[i] as cell
        , coalesce(sum(coalesce(dr.cell_colspans[i], 1)) over (
            partition by dr.accession, dr.row_index order by i rows between unbounded preceding and 1 preceding), 0)
            as column_start
        , coalesce(dr.cell_colspans[i], 1) as column_span
    from {{ ref('stg_filed_document_row') }} dr
    , range(1, dr.cell_count + 1) t(i)
    where exists (
        select 1 from printed_table pt where pt.accession = dr.accession and pt.table_index = dr.table_index
    )
)

, fair_value_column as (
    select accession, table_index, column_start
    from (
        select g.accession, g.table_index, g.column_start, count(*) as facts
        from {{ ref('stg_filed_fact_placement') }} pl
        join grid g on g.accession = pl.accession and g.row_index = pl.row_index and g.cell_index = pl.cell_index
        join {{ ref('concept_map') }} m on m.field = 'fair_value' and pl.concept like '%:' || m.concept_local
        group by g.accession, g.table_index, g.column_start
    )
    qualify row_number() over (partition by accession, table_index order by facts desc, column_start) = 1
)

, located as (
    select
        t.accession
        , t.context_id
        , p.row_index as printed_row_index
        , d.table_index
        , f.column_start as fair_value_column
        , g.cell as printed_cell
    from target t
    left join printed_row p on p.accession = t.accession and p.context_id = t.context_id
    left join {{ ref('stg_filed_document_row') }} d on d.accession = p.accession and d.row_index = p.row_index
    left join fair_value_column f on f.accession = d.accession and f.table_index = d.table_index
    left join grid g
        on g.accession = p.accession and g.row_index = p.row_index
        and f.column_start >= g.column_start and f.column_start < g.column_start + g.column_span
)

select
    accession
    , context_id
    , printed_row_index
    , table_index
    , fair_value_column
    , printed_cell
    , coalesce(regexp_full_match(regexp_replace(printed_cell, '[\s\x{00A0}$(),]', '', 'g'), '[-\x{2013}\x{2014}]|0+(\.0+)?'),
               false) as prints_dash_or_zero
from located
