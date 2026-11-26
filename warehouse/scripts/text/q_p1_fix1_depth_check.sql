-- Slice P fix round 1, 2026-11-26: where the depth inference can mislead. Per fund, published positions whose kept
-- depth-1 heading has, between it and the position, a lone heading (a run of 1) other than the position's depth-0
-- heading. Such a lone heading is either an earlier sibling at depth 0 (harmless) or a heading of the upper level whose
-- run had no lower heading under it (then depth 1 shows an older upper heading). Structure cannot tell the two apart.
-- Read-only.
with p as (
    select p.cik, p.accession, p.context_id, p.row_index, s.schedule_seq
    from int_page_position p join int_page_schedule s using (accession, table_index)
    where p.is_published and p.placement_status = 'one_row'
)
, d as (
    select p.*, d0.heading_row_index as d0_row, d1.heading_row_index as d1_row
    from p
    left join int_position_heading d0 on d0.accession = p.accession and d0.context_id = p.context_id and d0.heading_level = 0
    left join int_position_heading d1 on d1.accession = p.accession and d1.context_id = p.context_id and d1.heading_level = 1
)
select cik, count(*) as positions, count(d1_row) as with_depth_1
    , count(*) filter (where d1_row is not null and exists (
        select 1 from int_page_heading h where h.accession = d.accession and h.schedule_seq = d.schedule_seq
          and h.run_length = 1 and h.row_index > d.d1_row and h.row_index < d.row_index and h.row_index <> d.d0_row)) as lone_heading_between
    , count(*) filter (where d0_row is not null and (select h.run_length from int_page_heading h
        where h.accession = d.accession and h.row_index = d.d0_row) = 1) as depth_0_is_lone
from d group by 1 order by 1
