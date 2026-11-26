-- Slice R phase 2 fix round 1, item 4: one filing, printed rows 824 to 837. For each position placed on a row: the
-- row the position is placed on (int_page_position, by its fair value fact), and every fact of the position's context
-- whose concept is a rate or fair value, with the row its placement is printed on and the displayed text. Read-only.
with pos as (
  select accession, context_id, row_index as position_row, fair_value_fact_id
  from int_page_position
  where accession = '0001803498-22-000021' and placement_status = 'one_row' and row_index between 824 and 837
)
select p.position_row, right(p.context_id, 30) as ctx, f.concept_local, f.value_numeric, fp.row_index as fact_row,
  fp.displayed_text, f.fact_id = p.fair_value_fact_id as is_fv_fact
from pos p
join stg_filed_fact f on f.accession = p.accession and f.context_id = p.context_id
left join stg_filed_fact_placement fp on fp.accession = f.accession and fp.fact_id = f.fact_id
where f.concept_local ilike '%rate%' or f.concept_local ilike '%spread%' or f.fact_id = p.fair_value_fact_id
order by p.position_row, f.concept_local
