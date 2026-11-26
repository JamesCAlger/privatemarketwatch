-- Slice P fix round 1, 2026-11-26: schedule starts of one filing with their titles and signatures, and the published
-- state of the positions in each table. Read-only. Change the accession to look at another filing.
select s.table_index, s.schedule_seq, s.starts_schedule, left(s.title_key, 60) as title_key, left(s.table_signature, 120) as sig
    , (select bool_or(p.is_published) from int_page_position p where p.accession = s.accession and p.table_index = s.table_index) as any_pub
    , (select bool_and(p.is_published) from int_page_position p where p.accession = s.accession and p.table_index = s.table_index and p.placement_status = 'one_row') as all_pub
from int_page_schedule s
where s.accession = '0001803498-24-000007'
  and (s.starts_schedule or s.table_index in (34, 35, 36, 141, 142, 143)
       or s.table_index in (select table_index from int_page_schedule where accession = '0001803498-24-000007' and title_key is not null))
order by s.table_index
