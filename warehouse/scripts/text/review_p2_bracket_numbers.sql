-- Review P fix round 1: cells of shape footnote_mark per fund: how many hold a placed fact (bracketed numbers such as
-- '(110)' read as footnote marks), by concept and header; and how many hold none.
with c as (
  select i.cik, cc.accession, cc.row_index, cc.cell_index, cc.text, cc.header_signature, cc.column_rule,
    (select min(pl.concept) from stg_filed_fact_placement pl where pl.accession=cc.accession and coalesce(pl.row_index,pl.shown_row_index)=cc.row_index and coalesce(pl.cell_index,pl.shown_cell_index)=cc.cell_index) concept
  from int_page_cell_column cc join int_page_table i using (accession, table_index) where cc.shape='footnote_mark'
)
select cik, concept is not null has_fact, coalesce(concept,'-') concept, coalesce(header_signature,'-') hdr, count(*) n, min(text) ex1, max(text) ex2
from c group by all having count(*) >= 20 order by cik, n desc
