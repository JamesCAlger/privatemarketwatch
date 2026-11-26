-- Slice P fix round 2, 2026-11-26: the headings above one position in its schedule (nearest 25), with depth, level,
-- continuation flags and run. Read-only. Change the accession and context in the first CTE.
with pk as (
    select p.accession, p.row_index, s.schedule_seq
    from int_page_position p join int_page_schedule s using (accession, table_index)
    where p.accession = '0001803498-23-000021' and p.context_id = 'c-598'
)
select h.row_index, h.table_index, left(h.text, 60) as text, h.norm_text, h.run_length, h.run_position, h.depth_from_bottom
    , h.level, h.is_page_top_run, h.is_continuation
from pk join int_page_heading h on h.accession = pk.accession and h.schedule_seq = pk.schedule_seq and h.row_index < pk.row_index
order by h.row_index desc limit 25
