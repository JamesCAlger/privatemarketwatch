-- Slice R phase 2 fix round 1, item 4: every interest-rate fact placed on printed rows 824 to 837 of the filing, with
-- the context it belongs to and the row of that context's position; and the raw cells of rows 825 to 827. Read-only.
select 'fact' as kind, fp.row_index, f.concept_local, fp.displayed_text, right(f.context_id, 30) as ctx,
  p.row_index as context_position_row, null as cells
from stg_filed_fact_placement fp
join stg_filed_fact f on f.accession = fp.accession and f.fact_id = fp.fact_id
left join int_page_position p on p.accession = f.accession and p.context_id = f.context_id and p.placement_status = 'one_row'
where fp.accession = '0001803498-22-000021' and fp.row_index between 824 and 837 and f.concept_local = 'InvestmentInterestRate'
union all
select 'row', row_index, null, null, null, null, cast(cells as varchar)
from stg_filed_document_row where accession = '0001803498-22-000021' and row_index between 825 and 827
order by 1, 2
