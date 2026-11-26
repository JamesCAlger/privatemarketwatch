-- Review P fix round 1: published positions whose kept stack holds the same heading text (normalised: lowercased,
-- '(continued)', footnote marks, punctuation and spaces removed) at two depths, or a text that is a prefix of the depth
-- below it (e.g. 'Structured Finance Obligations' over 'Structured Finance Obligations - Debt'). Per fund and depth pair.
with k as (
  select p.cik, ph.accession, ph.context_id, ph.heading_level, ph.text,
    regexp_replace(regexp_replace(replace(lower(ph.text),'(continued)',''),'\(\s*[a-z0-9]{1,3}\s*\)','','g'),'[^a-z0-9]','','g') as t
  from int_position_heading ph join int_page_position p using (accession, context_id) where p.is_published
)
select a.cik, a.heading_level as lo, b.heading_level as hi,
  count(*) filter (where a.t = b.t) as same_text,
  count(*) filter (where a.t <> b.t and starts_with(a.t, b.t)) as hi_prefix_of_lo,
  count(distinct a.accession) filter (where a.t = b.t or starts_with(a.t, b.t)) as filings,
  min(a.accession || ' ' || a.context_id || ' ' || left(a.text,30) || ' <- ' || left(b.text,30)) filter (where a.t = b.t or starts_with(a.t,b.t)) ex
from k a join k b on b.accession=a.accession and b.context_id=a.context_id and b.heading_level > a.heading_level
group by 1,2,3 having count(*) filter (where a.t = b.t or starts_with(a.t,b.t)) > 0 order by 1,2,3
