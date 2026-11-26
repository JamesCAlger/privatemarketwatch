-- The column unit of a filing, the thing the next slice bundles (text slice P3, 2026-11-26; spec section 4.1). One
-- row per (accession, header_signature) of int_page_column. Decides nothing: it counts.
--
-- n_tables: schedule tables of the filing that have a leaf with this signature.
-- data_cells: cells of int_page_cell_column under this signature; n_<shape>: how many of them have each shape (macro
-- page_cell_shape), share_<shape> = n_<shape> / data_cells (null when data_cells is 0).
-- placed_facts: placements of the filed layer (stg_filed_fact_placement; a hidden fact counts in the cell that shows
-- it) whose row and cell is a data cell under this signature. placed_concepts: those placements counted by concept,
-- written 'concept=n' joined by '; ', most frequent first, then by concept.
with leaf as (
    select accession, header_signature, min(cik) as cik, min(report_date) as report_date
        , count(distinct table_index) as n_tables
    from {{ ref('int_page_column') }}
    group by 1, 2
)

, cell as (
    select
        accession
        , header_signature
        , count(*) as data_cells
        , count(*) filter (where shape = 'number') as n_number
        , count(*) filter (where shape = 'percent') as n_percent
        , count(*) filter (where shape = 'date') as n_date
        , count(*) filter (where shape = 'text') as n_text
        , count(*) filter (where shape = 'empty_marker') as n_empty_marker
        , count(*) filter (where shape = 'footnote_mark') as n_footnote_mark
    from {{ ref('int_page_cell_column') }}
    where header_signature is not null
    group by 1, 2
)

, placed as (
    select cc.accession, cc.header_signature, pl.concept, count(*) as n
    from {{ ref('stg_filed_fact_placement') }} pl
    join {{ ref('int_page_cell_column') }} cc
        on cc.accession = pl.accession
        and cc.row_index = coalesce(pl.row_index, pl.shown_row_index)
        and cc.cell_index = coalesce(pl.cell_index, pl.shown_cell_index)
    where cc.header_signature is not null
    group by 1, 2, 3
)

, placed_summary as (
    select accession, header_signature, sum(n) as placed_facts
        , string_agg(concept || '=' || n, '; ' order by n desc, concept) as placed_concepts
    from placed
    group by 1, 2
)

select
    l.accession
    , l.header_signature
    , l.cik
    , l.report_date
    , l.n_tables
    , coalesce(c.data_cells, 0) as data_cells
    , coalesce(c.n_number, 0) as n_number
    , coalesce(c.n_percent, 0) as n_percent
    , coalesce(c.n_date, 0) as n_date
    , coalesce(c.n_text, 0) as n_text
    , coalesce(c.n_empty_marker, 0) as n_empty_marker
    , coalesce(c.n_footnote_mark, 0) as n_footnote_mark
    , c.n_number / nullif(c.data_cells, 0) as share_number
    , c.n_percent / nullif(c.data_cells, 0) as share_percent
    , c.n_date / nullif(c.data_cells, 0) as share_date
    , c.n_text / nullif(c.data_cells, 0) as share_text
    , c.n_empty_marker / nullif(c.data_cells, 0) as share_empty_marker
    , c.n_footnote_mark / nullif(c.data_cells, 0) as share_footnote_mark
    , coalesce(p.placed_facts, 0) as placed_facts
    , p.placed_concepts
from leaf l
left join cell c on c.accession = l.accession and c.header_signature = l.header_signature
left join placed_summary p on p.accession = l.accession and p.header_signature = l.header_signature
