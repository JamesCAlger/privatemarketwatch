-- Decides which heading rows sit above each position's printed row (text slice P4, 2026-11-26; by depth in fix round 1,
-- by level in fix round 2). One row per (accession, context_id, heading_level). Assigns no meaning to a heading.
--
-- For each position with a printed row (int_page_position placement_status one_row), only headings of the same filing
-- and the same schedule (int_page_schedule.schedule_seq of the position's table) whose row_index is below the
-- position's (above it on the page) are looked at. Headings carry across the page tables of one schedule, never into
-- the next schedule.
-- For each level L from 0 to 3 (int_page_heading.level, the level of the heading's normalised text in the filing): the
-- nearest such heading at level L, dropped if a heading of a higher level that is not a continuation
-- (int_page_heading.is_continuation false) lies between it and the position. A new section therefore drops the old
-- industry; a page-top repeat of the running stack ("Equity (continued)") does not, and counts as its text at its
-- level. Headings above level 3 are not taken, but they still drop the lower ones.
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
    select accession, schedule_seq, row_index, table_index, col_start, text, is_continued, is_continuation, run_length
        , depth_from_bottom, level
    from {{ ref('int_page_heading') }}
)

{% for l in range(4) %}
, at_level_{{ l }} as (
    select p.*, h.row_index as heading_row_index
    from placed_position p
    asof join (select * from heading where level = {{ l }}) h
        on h.accession = p.accession and h.schedule_seq = p.schedule_seq and h.row_index < p.row_index
)

, reset_{{ l }} as (
    select p.accession, p.context_id, h.row_index as reset_row_index
    from placed_position p
    asof join (select * from heading where level > {{ l }} and not is_continuation) h
        on h.accession = p.accession and h.schedule_seq = p.schedule_seq and h.row_index < p.row_index
)
{% endfor %}

, kept as (
{% for l in range(4) %}
    select a.accession, a.context_id, a.is_published, a.row_index, a.table_index, {{ l }} as heading_level
        , a.heading_row_index
    from at_level_{{ l }} a
    left join reset_{{ l }} r on r.accession = a.accession and r.context_id = a.context_id
    where r.reset_row_index is null or a.heading_row_index > r.reset_row_index
    {% if not loop.last %}union all{% endif %}
{% endfor %}
)

select
    k.accession
    , k.context_id
    , k.is_published
    , k.heading_level
    , row_number() over (partition by k.accession, k.context_id order by k.heading_row_index desc) as heading_rank
    , k.heading_row_index
    , h.table_index as heading_table_index
    , k.row_index - k.heading_row_index as distance_rows
    , h.table_index = k.table_index as same_table
    , h.col_start
    , h.text
    , h.is_continued
    , h.is_continuation
    , h.run_length
    , h.depth_from_bottom
from kept k
join heading h on h.accession = k.accession and h.row_index = k.heading_row_index
