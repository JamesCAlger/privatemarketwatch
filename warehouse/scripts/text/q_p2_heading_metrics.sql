-- Slice P fix round 2, 2026-11-26: heading stack checks per fund on published positions (int_position_heading,
-- column heading_level). Read-only. Normalised text: lower case, '(continued)', bracketed marks and every character that
-- is not a letter or digit removed.
--   same_text_two_levels  positions whose kept headings hold one normalised text at two levels.
--   affiliation_pair      positions whose level-1 and level-2 headings both name 'controlled' or 'affiliated' with
--                         different normalised texts (a sibling section taken as a parent).
--   section_not_kept      positions with a heading naming 'controlled' above them in their schedule, none kept.
--   no_level_0            positions with no level-0 heading kept.
--   level0_is_level1_elsewhere  positions whose level-0 text is kept at level 1 for another position of the filing.
with k as (
    select p.cik, ph.accession, ph.context_id, ph.heading_level as lvl, ph.text
        , regexp_replace(regexp_replace(replace(lower(ph.text), '(continued)', ''), '\(\s*[a-z0-9]{1,3}\s*\)', '', 'g'),
                         '[^a-z0-9]', '', 'g') as t
    from int_position_heading ph join int_page_position p using (accession, context_id)
    where p.is_published
)
, pos as (
    select p.cik, p.accession, p.context_id, p.row_index, s.schedule_seq
    from int_page_position p join int_page_schedule s using (accession, table_index)
    where p.is_published and p.placement_status = 'one_row'
)
, l1_text as (select distinct accession, t from k where lvl = 1)
select pos.cik
    , count(*) as positions
    , count(*) filter (where exists (select 1 from k a join k b on b.accession = a.accession and b.context_id = a.context_id
        and b.lvl > a.lvl and b.t = a.t where a.accession = pos.accession and a.context_id = pos.context_id)) as same_text_two_levels
    , count(*) filter (where exists (select 1 from k a join k b on b.accession = a.accession and b.context_id = a.context_id
        and a.lvl = 1 and b.lvl = 2 and a.t <> b.t
        where a.accession = pos.accession and a.context_id = pos.context_id
          and regexp_matches(lower(a.text), 'controlled|affiliated') and regexp_matches(lower(b.text), 'controlled|affiliated'))) as affiliation_pair
    , count(*) filter (where exists (select 1 from int_page_heading h where h.accession = pos.accession
            and h.schedule_seq = pos.schedule_seq and h.row_index < pos.row_index and lower(h.text) like '%controlled%')
        and not exists (select 1 from k where k.accession = pos.accession and k.context_id = pos.context_id
            and lower(k.text) like '%controlled%')) as section_not_kept
    , count(*) filter (where not exists (select 1 from k where k.accession = pos.accession and k.context_id = pos.context_id
        and k.lvl = 0)) as no_level_0
    , count(*) filter (where exists (select 1 from k join l1_text l on l.accession = k.accession and l.t = k.t
        where k.accession = pos.accession and k.context_id = pos.context_id and k.lvl = 0)) as level0_is_level1_elsewhere
from pos group by 1 order by 1
