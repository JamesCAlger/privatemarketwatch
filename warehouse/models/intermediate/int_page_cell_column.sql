-- Decides the column unit of every data cell of the schedule tables that have a header (text slice P3, 2026-11-26;
-- rules revised in fix round 1). One row per non-empty cell (int_page_cell) in a row below the table's last header
-- line (int_page_table.header_last_row_in_table): (accession, row_index, cell_index). Cells of tables without a header
-- (header_status none or ambiguous) have no row here.
--
-- shape: macro page_cell_shape of the cell's text (empty_marker, footnote_mark, date, percent, number, text), with one
-- change (fix round 2): the macro calls a single bracketed group of 1 to 3 digits ('(110)', '(4)') a footnote mark, but
-- it can be a negative amount. Such a cell (exact test regexp_full_match(text, '\(\s*\d{1,3}\s*\)')) is a number when
-- a filed fact is placed in it (stg_filed_fact_placement; a hidden fact counts in the cell that shows it). With no fact
-- placed, it is a number when its column holds placed numeric facts in other cells, otherwise a footnote mark. Its
-- column here: the same table signature (int_page_schedule) and zone signature in the filing, and the same side of the
-- zone leaf's printed columns (inside them, or in the gap after them where unheaded footnote marks sit). 'Placed
-- numeric facts': other cells of that column with a fact placed and macro shape number. Two or more groups ('(4)(5)')
-- and groups with letters ('(a)') stay footnote marks.
-- currency marker: a cell whose whole text is one currency symbol (Unicode currency-symbol class, e.g. '$', '€', '£',
-- '₣') optionally preceded by one to three capital letters ('A$', 'NZ$', 'US$'), or the text 'kr' (any case). Exact
-- test: regexp_full_match(text, '[A-Z]{0,3}\p{Sc}|[Kk][Rr]').
-- column_rule, the first that applies:
--   none_row_width_differs  the cell's row has row_width_ok false (int_page_cell): its cells are laid out unlike the
--                           table's rows, so no column is given rather than a wrong one.
--   prefix_of_next          the cell is a currency marker and the next non-empty cell of its row (next cell_index) has
--                           shape number: it takes that cell's column ("A$" then "9,900" both go to the column of the
--                           number, wherever the marker's own column falls).
--   trailing_footnote       the cell has shape footnote_mark and starts after its zone leaf's printed columns (in the
--                           gap between the leaf's col_end and the next leaf): an unheaded column of footnote marks.
--                           header_signature '#footnote_marks' (no printed header seen holds a '#'); column_col_start and
--                           column_index null.
--   zone                    the leaf of int_page_column whose zone (col_start to zone_end) contains the cell's
--                           col_start. Example: under "Par Amount/Units" at columns 39-44, a "$" at 39 and its number at
--                           40 both get that header.
--   none_left_of_first_leaf no zone contains the cell's col_start.
with header_table as (
    select accession, table_index, header_last_row_in_table
    from {{ ref('int_page_table') }}
    where header_status in ('one_line', 'two_lines')
)

, fact_cell as (
    select distinct accession, coalesce(row_index, shown_row_index) as row_index
        , coalesce(cell_index, shown_cell_index) as cell_index
    from {{ ref('stg_filed_fact_placement') }}
)

, zoned as (
    select
        c.accession
        , c.row_index
        , c.cell_index
        , c.table_index
        , c.row_in_table
        , c.col_start
        , c.text
        , {{ page_cell_shape('c.text') }} as macro_shape
        , regexp_full_match(c.text, '\(\s*\d{1,3}\s*\)') as is_bracketed_digits
        , f.row_index is not null as has_fact
        , s.table_signature
        , c.row_fact_count
        , c.row_width_ok
        , regexp_full_match(c.text, '[A-Z]{0,3}\p{Sc}|[Kk][Rr]') as is_currency_marker
        , col.col_start as zone_col_start
        , col.col_end as zone_col_end
        , col.column_index as zone_column_index
        , col.header_signature as zone_signature
    from {{ ref('int_page_cell') }} c
    join header_table h
        on h.accession = c.accession and h.table_index = c.table_index and c.row_in_table > h.header_last_row_in_table
    left join {{ ref('int_page_column') }} col
        on col.accession = c.accession and col.table_index = c.table_index
        and c.col_start between col.col_start and col.zone_end
    left join {{ ref('int_page_schedule') }} s on s.accession = c.accession and s.table_index = c.table_index
    left join fact_cell f on f.accession = c.accession and f.row_index = c.row_index and f.cell_index = c.cell_index
)

, numeric_column as (
    -- columns (table signature, zone signature, side of the leaf's printed columns) holding placed numeric facts
    select distinct accession, table_signature, zone_signature, col_start > zone_col_end as in_gap
    from zoned
    where has_fact and macro_shape = 'number' and zone_signature is not null
)

, shaped as (
    select
        z.*
        , case
            when z.macro_shape = 'footnote_mark' and z.is_bracketed_digits and (z.has_fact or nc.accession is not null)
                then 'number'
            else z.macro_shape
        end as shape
    from zoned z
    left join numeric_column nc
        on nc.accession = z.accession and nc.table_signature = z.table_signature and nc.zone_signature = z.zone_signature
        and nc.in_gap = (z.col_start > z.zone_col_end)
)

, with_next as (
    select
        z.*
        , lead(z.shape) over w as next_shape
        , lead(z.zone_col_start) over w as next_col_start
        , lead(z.zone_column_index) over w as next_column_index
        , lead(z.zone_signature) over w as next_signature
    from shaped z
    window w as (partition by z.accession, z.row_index order by z.cell_index)
)

, ruled as (
    select
        n.*
        , case
            when not n.row_width_ok then 'none_row_width_differs'
            when n.is_currency_marker and n.next_shape = 'number' and n.next_col_start is not null then 'prefix_of_next'
            when n.shape = 'footnote_mark' and n.zone_col_start is not null and n.col_start > n.zone_col_end
                then 'trailing_footnote'
            when n.zone_col_start is not null then 'zone'
            else 'none_left_of_first_leaf'
        end as column_rule
    from with_next n
)

select
    accession
    , row_index
    , cell_index
    , table_index
    , row_in_table
    , col_start
    , text
    , shape
    , row_fact_count
    , column_rule
    , case column_rule when 'zone' then zone_col_start when 'prefix_of_next' then next_col_start end as column_col_start
    , case column_rule when 'zone' then zone_column_index when 'prefix_of_next' then next_column_index end
        as column_index
    , case column_rule
        when 'zone' then zone_signature
        when 'prefix_of_next' then next_signature
        when 'trailing_footnote' then '#footnote_marks'
    end as header_signature
    , zone_signature
from ruled
