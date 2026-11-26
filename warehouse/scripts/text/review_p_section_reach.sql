-- Review slice P: published positions whose 4 nearest headings contain no section heading (text naming an
-- affiliation class, 'controlled'), versus whether such a heading exists anywhere above them in the filing.
with sec as (select accession, row_index from int_page_heading where lower(text) like '%controlled%')
, p as (select p.cik, p.accession, p.context_id, p.row_index from int_page_position p where p.is_published and p.placement_status='one_row')
select p.cik, count(*) n,
  count(*) filter (where not exists (select 1 from int_position_heading ph where ph.accession=p.accession and ph.context_id=p.context_id and lower(ph.text) like '%controlled%')) no_section_in_4,
  count(*) filter (where exists (select 1 from sec s where s.accession=p.accession and s.row_index < p.row_index)) section_exists_above
from p group by 1 order by 1
