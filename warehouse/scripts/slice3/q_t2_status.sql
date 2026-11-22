-- Slice 3 Task 2: int_field_read counts per fund and field (read, absent, unresolved, nil), all positions and published.
select r.cik, r.field
    , count(*) as rows
    , count(*) filter (where r.status = 'read' and not r.is_nil) as read_value
    , count(*) filter (where r.is_nil) as read_nil
    , count(*) filter (where r.status = 'absent') as absent
    , count(*) filter (where r.status = 'unresolved') as unresolved
    , count(*) filter (where s.is_published) as pub_rows
    , count(*) filter (where s.is_published and r.status = 'read' and not r.is_nil) as pub_read_value
    , count(*) filter (where s.is_published and r.is_nil) as pub_nil
    , count(*) filter (where s.is_published and r.status = 'absent') as pub_absent
    , count(*) filter (where s.is_published and r.status = 'unresolved') as pub_unresolved
from int_field_read r
join int_source_row s on s.accession = r.accession and s.context_id = r.context_id
group by all
order by r.field, r.cik
