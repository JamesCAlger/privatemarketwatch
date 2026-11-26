-- Slice P fix round 1, 2026-11-26: published positions with a '...controlled...' heading above them in their schedule
-- but none among their kept headings: the headings kept, and the nearest such heading with its depth. Read-only.
with miss as (
    select p.cik, p.accession, p.context_id, p.row_index, p.table_index
    from int_page_position p
    join int_page_schedule s using (accession, table_index)
    where p.is_published and p.placement_status = 'one_row'
      and exists (select 1 from int_page_heading h where h.accession = p.accession and h.schedule_seq = s.schedule_seq
                  and h.row_index < p.row_index and lower(h.text) like '%controlled%')
      and not exists (select 1 from int_position_heading ph where ph.accession = p.accession and ph.context_id = p.context_id
                      and lower(ph.text) like '%controlled%')
)
select m.cik, m.accession, count(*) as n, min(m.row_index) as first_row
    , (select string_agg(ph.heading_level || ':' || left(ph.text, 40), ' | ' order by ph.heading_level)
       from int_position_heading ph where ph.accession = m.accession and ph.context_id = min(m.context_id)) as kept
    , (select string_agg(h.row_index || ' d' || h.depth_from_bottom || ' L' || h.run_length || ':' || left(h.text, 45), ' | ' order by h.row_index desc)
       from int_page_heading h where h.accession = m.accession and h.row_index < min(m.row_index) and h.row_index > min(m.row_index) - 120) as above
from miss m group by m.cik, m.accession order by 1, 2
