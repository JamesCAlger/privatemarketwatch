-- Decides which heading rows sit above each position's printed row (text slice P4, 2026-11-26). One row per
-- (accession, context_id, heading_rank). Assigns no meaning to a heading.
--
-- For each position with a printed row (int_page_position placement_status one_row): the heading rows of
-- int_page_heading in the same filing whose row_index is below the position's row_index (above it on the page), the
-- nearest first, at most 4. Headings carry across the schedule's page tables in document row order: a position at the
-- top of a page table without a heading of its own gets the headings of the tables before it. heading_rank 1 is the
-- nearest; distance_rows is the position's row_index minus the heading's (document rows, counting rows of every
-- table in between); same_table says whether the heading sits in the position's own table. A position with no
-- heading above it in its filing has no row.
with placed_position as (
    select accession, context_id, is_published, row_index, table_index
    from {{ ref('int_page_position') }}
    where placement_status = 'one_row'
)

, heading as (
    select
        accession
        , row_index
        , table_index
        , col_start
        , text
        , is_continued
        , row_number() over (partition by accession order by row_index) as heading_seq
    from {{ ref('int_page_heading') }}
)

, nearest as (
    select p.accession, p.context_id, p.is_published, p.row_index, p.table_index, h.heading_seq as nearest_seq
    from placed_position p
    asof join heading h on h.accession = p.accession and h.row_index < p.row_index
)

select
    n.accession
    , n.context_id
    , n.is_published
    , n.nearest_seq - h.heading_seq + 1 as heading_rank
    , h.row_index as heading_row_index
    , h.table_index as heading_table_index
    , n.row_index - h.row_index as distance_rows
    , h.table_index = n.table_index as same_table
    , h.col_start
    , h.text
    , h.is_continued
from nearest n
join heading h
    on h.accession = n.accession and h.heading_seq between n.nearest_seq - 3 and n.nearest_seq
