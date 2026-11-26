-- Review P fix round 1: HPS/BCRED/Blue Owl published positions whose depth-1 heading already names an affiliation
-- ('controlled' or 'affiliated'): what depth 2 holds. A depth-2 heading that is an asset class unrelated to depth 1
-- is a stale carry.
with k as (
  select p.cik, ph.accession, ph.context_id, ph.heading_level, ph.text
  from int_position_heading ph join int_page_position p using (accession, context_id) where p.is_published
)
select a.cik, left(a.text,45) d1, left(b.text,45) d2, count(*) n, count(distinct a.accession) filings, min(a.accession) ex
from k a join k b on b.accession=a.accession and b.context_id=a.context_id and b.heading_level=2
where a.heading_level=1 and (lower(a.text) like '%controlled%' or lower(a.text) like '%affiliated%')
  and a.cik in ('0001838126','0001812554','0001803498')
  and not starts_with(regexp_replace(lower(a.text),'[^a-z]','','g'), regexp_replace(lower(regexp_replace(b.text,'\(.*?\)','','g')),'[^a-z]','','g'))
group by 1,2,3 order by 1, n desc
