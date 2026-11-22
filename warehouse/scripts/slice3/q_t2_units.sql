-- Slice 3 Task 2: units seen per field on read rows, with counts (all positions; published in its own column).
select r.field, r.unit, count(*) as rows, count(*) filter (where s.is_published) as published
    , count(distinct r.cik) as funds, min(r.cik) as min_cik, max(r.cik) as max_cik
from int_field_read r
join int_source_row s on s.accession = r.accession and s.context_id = r.context_id
where r.status = 'read'
group by all
order by r.field, rows desc
