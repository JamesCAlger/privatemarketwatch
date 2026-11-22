-- Slice 3 Task 2: read rows (not nil) with no printed text, per fund and field, with whether the fact has a placement.
select r.cik, r.field, count(*) as n
    , count(*) filter (where pl.fact_id is null) as no_placement
    , count(*) filter (where pl.in_hidden) as hidden
    , count(*) filter (where pl.in_hidden and pl.shown_row_index is null) as hidden_not_shown
    , count(*) filter (where not pl.in_hidden and pl.row_index is null) as shown_outside_row
from int_field_read r
left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
where r.status = 'read' and not r.is_nil and r.printed_text is null
group by all order by 1, 2
