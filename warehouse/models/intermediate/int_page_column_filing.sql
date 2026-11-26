-- The column unit of a filing, the thing the next slice bundles (text slice P3, 2026-11-26; spec section 4.1; re-keyed in
-- fix round 1). One row per (accession, table_signature, header_signature): the same header in two kinds of table (the
-- fund's schedule, a joint venture's schedule, a table of unfunded commitments) is two units. Decides nothing: it
-- counts.
--
-- table_signature: int_page_schedule.table_signature, the table's leaf signatures in column order joined by '|'.
-- header_signature: the cell's column (int_page_cell_column), including the unheaded '#footnote_marks' column.
-- n_tables: tables of the filing with this table_signature that hold a cell under this header_signature, or a leaf.
-- data_cells: cells under the unit; n_<shape>: how many of each shape (macro page_cell_shape). n_footnote_mark is given
-- separately and left out of the shares: share_<shape> = n_<shape> / (data_cells - n_footnote_mark), null when that is 0.
-- placed_facts: placements of the filed layer (stg_filed_fact_placement; a hidden fact counts in the cell that shows
-- it) whose row and cell is a data cell of the unit. placed_concepts: those placements counted by concept, written
-- 'concept=n' joined by '; ', most frequent first, then by concept.
with table_key as (
    select accession, table_index, cik, report_date, table_signature
    from {{ ref('int_page_schedule') }}
    where table_signature is not null
)

, unit_cell as (
    select k.accession, k.table_signature, k.cik, k.report_date, cc.table_index, cc.header_signature, cc.row_index
        , cc.cell_index, cc.shape
    from {{ ref('int_page_cell_column') }} cc
    join table_key k on k.accession = cc.accession and k.table_index = cc.table_index
    where cc.header_signature is not null
)

, unit as (
    select k.accession, k.table_signature, c.header_signature, min(k.cik) as cik, min(k.report_date) as report_date
        , count(distinct k.table_index) as n_tables
    from {{ ref('int_page_column') }} c
    join table_key k on k.accession = c.accession and k.table_index = c.table_index
    group by 1, 2, 3
    union
    select accession, table_signature, header_signature, min(cik), min(report_date), count(distinct table_index)
    from unit_cell
    where header_signature = '#footnote_marks'
    group by 1, 2, 3
)

, cell as (
    select
        accession
        , table_signature
        , header_signature
        , count(*) as data_cells
        , count(*) filter (where shape = 'number') as n_number
        , count(*) filter (where shape = 'percent') as n_percent
        , count(*) filter (where shape = 'date') as n_date
        , count(*) filter (where shape = 'text') as n_text
        , count(*) filter (where shape = 'empty_marker') as n_empty_marker
        , count(*) filter (where shape = 'footnote_mark') as n_footnote_mark
    from unit_cell
    group by 1, 2, 3
)

, placed as (
    select u.accession, u.table_signature, u.header_signature, pl.concept, count(*) as n
    from {{ ref('stg_filed_fact_placement') }} pl
    join unit_cell u
        on u.accession = pl.accession
        and u.row_index = coalesce(pl.row_index, pl.shown_row_index)
        and u.cell_index = coalesce(pl.cell_index, pl.shown_cell_index)
    group by 1, 2, 3, 4
)

, placed_summary as (
    select accession, table_signature, header_signature, sum(n) as placed_facts
        , string_agg(concept || '=' || n, '; ' order by n desc, concept) as placed_concepts
    from placed
    group by 1, 2, 3
)

select
    u.accession
    , u.table_signature
    , u.header_signature
    , u.cik
    , u.report_date
    , u.n_tables
    , coalesce(c.data_cells, 0) as data_cells
    , coalesce(c.n_number, 0) as n_number
    , coalesce(c.n_percent, 0) as n_percent
    , coalesce(c.n_date, 0) as n_date
    , coalesce(c.n_text, 0) as n_text
    , coalesce(c.n_empty_marker, 0) as n_empty_marker
    , coalesce(c.n_footnote_mark, 0) as n_footnote_mark
    , c.n_number / nullif(c.data_cells - c.n_footnote_mark, 0) as share_number
    , c.n_percent / nullif(c.data_cells - c.n_footnote_mark, 0) as share_percent
    , c.n_date / nullif(c.data_cells - c.n_footnote_mark, 0) as share_date
    , c.n_text / nullif(c.data_cells - c.n_footnote_mark, 0) as share_text
    , c.n_empty_marker / nullif(c.data_cells - c.n_footnote_mark, 0) as share_empty_marker
    , coalesce(p.placed_facts, 0) as placed_facts
    , p.placed_concepts
from unit u
left join cell c
    on c.accession = u.accession and c.table_signature = u.table_signature and c.header_signature = u.header_signature
left join placed_summary p
    on p.accession = u.accession and p.table_signature = u.table_signature and p.header_signature = u.header_signature
