-- Decides which heading rows sit above each position's printed row (text slice P4, 2026-11-26; rewritten in fix round
-- 1). One row per (accession, context_id, heading_depth). Assigns no meaning to a heading.
--
-- For each position with a printed row (int_page_position placement_status one_row), only headings of the same filing
-- and the same schedule (int_page_schedule.schedule_seq of the position's table) whose row_index is below the
-- position's (above it on the page) are looked at. Headings carry across the page tables of one schedule, never into
-- the next schedule.
-- For each depth d from 0 to 3 (int_page_heading.depth_from_bottom): the nearest such heading at depth d, kept only if
-- no heading of a greater depth lies between it and the position (a heading higher in a stack resets the ones below
-- it). Example: a section heading over an industry heading, then rows, then a second industry heading alone, then the
-- position: depth 0 is the second industry, depth 1 the section; the first industry is not taken. Headings deeper
-- than 3 are not taken, but they still reset the lower depths.
-- heading_rank: 1 for the kept heading nearest the position, 2 for the next, and so on. distance_rows: the position's
-- row_index minus the heading's (document rows, counting rows of every table in between). same_table: the heading
-- sits in the position's own table. A position with no heading kept has no row.
with placed_position as (
    select p.accession, p.context_id, p.is_published, p.row_index, p.table_index, s.schedule_seq
    from {{ ref('int_page_position') }} p
    join {{ ref('int_page_schedule') }} s on s.accession = p.accession and s.table_index = p.table_index
    where p.placement_status = 'one_row'
)

, heading as (
    select accession, schedule_seq, row_index, table_index, col_start, text, is_continued, run_length, depth_from_bottom
    from {{ ref('int_page_heading') }}
)

{% for d in range(4) %}
, at_depth_{{ d }} as (
    select p.*, h.row_index as heading_row_index
    from placed_position p
    asof join (select * from heading where depth_from_bottom = {{ d }}) h
        on h.accession = p.accession and h.schedule_seq = p.schedule_seq and h.row_index < p.row_index
)

, reset_{{ d }} as (
    select p.accession, p.context_id, h.row_index as reset_row_index
    from placed_position p
    asof join (select * from heading where depth_from_bottom > {{ d }}) h
        on h.accession = p.accession and h.schedule_seq = p.schedule_seq and h.row_index < p.row_index
)
{% endfor %}

, kept as (
{% for d in range(4) %}
    select a.accession, a.context_id, a.is_published, a.row_index, a.table_index, {{ d }} as heading_depth
        , a.heading_row_index
    from at_depth_{{ d }} a
    left join reset_{{ d }} r on r.accession = a.accession and r.context_id = a.context_id
    where r.reset_row_index is null or a.heading_row_index > r.reset_row_index
    {% if not loop.last %}union all{% endif %}
{% endfor %}
)

select
    k.accession
    , k.context_id
    , k.is_published
    , k.heading_depth
    , row_number() over (partition by k.accession, k.context_id order by k.heading_row_index desc) as heading_rank
    , k.heading_row_index
    , h.table_index as heading_table_index
    , k.row_index - k.heading_row_index as distance_rows
    , h.table_index = k.table_index as same_table
    , h.col_start
    , h.text
    , h.is_continued
    , h.run_length
from kept k
join heading h on h.accession = k.accession and h.row_index = k.heading_row_index
