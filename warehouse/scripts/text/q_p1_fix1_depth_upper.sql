-- Slice P fix round 1, 2026-11-26: an estimate of wrong depth-1 headings. A lone heading (run of 1) lying between a
-- position's depth-1 heading and the position, whose text is the top of a run of 2 or more somewhere in the same fund's
-- filings, is probably an upper-level heading that had no lower heading under it here; the position's depth-1 heading
-- is then an older one. Per fund: published positions affected, and examples. Read-only; an estimate, not a rule.
with upper_text as (
    select distinct cik, text from int_page_heading where run_length >= 2 and run_position = 1
)
, p as (
    select p.cik, p.accession, p.context_id, p.row_index, s.schedule_seq, d1.heading_row_index as d1_row, d1.text as d1_text
    from int_page_position p
    join int_page_schedule s using (accession, table_index)
    join int_position_heading d1 on d1.accession = p.accession and d1.context_id = p.context_id and d1.heading_level = 1
    where p.is_published and p.placement_status = 'one_row'
)
, hit as (
    select p.*, h.text as lone_upper_text
    from p
    join int_page_heading h on h.accession = p.accession and h.schedule_seq = p.schedule_seq and h.run_length = 1
        and h.row_index > p.d1_row and h.row_index < p.row_index
    join upper_text u on u.cik = p.cik and u.text = h.text
    qualify row_number() over (partition by p.accession, p.context_id order by h.row_index desc) = 1
)
select cik, count(*) as positions, min(left(d1_text, 35) || ' <shadowed by> ' || left(lone_upper_text, 35)) as ex1
    , max(left(d1_text, 35) || ' <shadowed by> ' || left(lone_upper_text, 35)) as ex2
from hit group by 1 order by 1
