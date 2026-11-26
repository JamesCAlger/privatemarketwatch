-- Review slice P: headings carried (any rank) from a table whose positions are published into a table of
-- unpublished positions or the reverse (main schedule <-> JV schedule boundary).
with tp as (
  select accession, table_index, bool_or(is_published) as any_pub, bool_and(is_published) as all_pub,
         min(report_date) rd
  from int_page_position where placement_status='one_row' group by 1,2
)
select p.cik, p.is_published as pos_pub, th.any_pub as head_table_pub, ph.heading_rank, count(*) n,
  min(p.accession || ' t' || p.table_index || ' <- t' || ph.heading_table_index || ' ' || left(ph.text,40)) ex,
  max(p.accession || ' t' || p.table_index || ' <- t' || ph.heading_table_index || ' ' || left(ph.text,40)) ex2
from int_page_position p
join int_position_heading ph on ph.accession=p.accession and ph.context_id=p.context_id and not ph.same_table
join tp th on th.accession=p.accession and th.table_index=ph.heading_table_index
where p.is_published <> th.any_pub
group by all order by 1,2,4
