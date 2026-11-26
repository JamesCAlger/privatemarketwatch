-- Slice P fix round 2, 2026-11-26: does the reset (a higher-level, non-continuation heading in between) drop a heading?
-- Per fund and level: placed positions with a heading at that level above them in their schedule, and how many of
-- those int_position_heading does not keep. Also headings by is_continuation and level change against
-- depth_from_bottom. Read-only.
with p as (
    select p.cik, p.accession, p.context_id, p.row_index, s.schedule_seq
    from int_page_position p join int_page_schedule s using (accession, table_index)
    where p.placement_status = 'one_row'
)
, lv as (select unnest([0, 1, 2, 3]) as l)
, cand as (
    select p.cik, p.accession, p.context_id, lv.l
        , (select max(h.row_index) from int_page_heading h where h.accession = p.accession and h.schedule_seq = p.schedule_seq
           and h.row_index < p.row_index and h.level = lv.l) as nearest
    from p cross join lv
)
select 'reset' as k, c.cik, c.l::varchar as a, count(nearest) as n1
    , count(*) filter (where nearest is not null and k.heading_row_index is null) as n2
from cand c left join int_position_heading k on k.accession = c.accession and k.context_id = c.context_id and k.heading_level = c.l
group by 1, 2, 3
union all
select 'heading', cik, is_continuation::varchar, count(*), count(*) filter (where level <> depth_from_bottom)
from int_page_heading group by 1, 2, 3
order by 1, 2, 3
