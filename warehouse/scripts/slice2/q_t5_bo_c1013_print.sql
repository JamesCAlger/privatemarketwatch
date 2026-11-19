-- Task 5, Blue Owl amendment: the printed rows that carry the facts of c-1012 and c-1013 (0001812554-26-000027), with
-- the rows either side, and every stored correction that names c-1013 in that filing.
with acc as (select '0001812554-26-000027' as accession)
, placed as (
    select distinct p.context_id, p.row_index
    from stg_filed_fact_placement p, acc
    where p.accession = acc.accession and p.context_id in ('c-1012', 'c-1013')
)
select 'placed' k, p.context_id, p.row_index, array_to_string(d.cells, ' | ') as text
from placed p join stg_filed_document_row d on d.accession = '0001812554-26-000027' and d.row_index = p.row_index
union all
select 'around', null, d.row_index, array_to_string(d.cells, ' | ')
from stg_filed_document_row d
where d.accession = '0001812554-26-000027' and d.row_index between 1448 and 1455
union all
select 'correction', c.context_id, null, c.kind || ' ' || c.store || ' ' || coalesce(c.value, '')
from stg_correction c where c.accession = '0001812554-26-000027' and c.context_id = 'c-1013'
order by 1, 3
