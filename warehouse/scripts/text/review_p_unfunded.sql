-- Review slice P: Blue Owl positions whose fair-value printed row is in a table whose header has 'unfunded'.
with t as (
  select distinct accession, table_index from int_page_column where header_signature like '%unfunded%'
)
select p.cik, p.report_date, p.is_published, count(*) as n
  , count(*) filter (where exists (select 1 from int_field_read f join stg_filed_fact_placement pl on pl.accession=f.accession and pl.fact_id=f.fact_id
        where f.accession=p.accession and f.context_id=p.context_id and f.field='cost' and f.status='read' and pl.row_index = p.row_index)) as cost_same_row
  , count(*) filter (where exists (select 1 from int_field_read f join stg_filed_fact_placement pl on pl.accession=f.accession and pl.fact_id=f.fact_id
        where f.accession=p.accession and f.context_id=p.context_id and f.field='cost' and f.status='read' and not pl.in_hidden)) as cost_placed_anywhere
  , min(p.context_id) as ex_context, min(p.accession) as ex_acc
from int_page_position p join t using (accession, table_index)
group by all order by 1,2,3
