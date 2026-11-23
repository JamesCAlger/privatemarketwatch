-- Slice 4 Task 2: per fund and new field of int_field_read, rows read (with a value), read nil, absent, unresolved
-- (by reason). All position rows, published or not; published counts beside.
select r.cik, r.field
    , count(*) as rows
    , count(*) filter (where r.status = 'read' and not r.is_nil) as read_value
    , count(*) filter (where r.status = 'read' and r.is_nil) as read_nil
    , count(*) filter (where r.status = 'absent') as absent
    , count(*) filter (where r.status = 'unresolved') as unresolved
    , string_agg(distinct case when r.status = 'unresolved' then r.reason end, ',') as unresolved_reasons
    , count(*) filter (where r.status = 'read' and r.fact_count > 1) as read_repeated
    , count(*) filter (where s.is_published) as published_rows
    , count(*) filter (where s.is_published and r.status = 'read' and not r.is_nil) as published_read_value
from int_field_read r
join int_source_row s on s.accession = r.accession and s.context_id = r.context_id
where r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread', 'maturity_date')
group by all
order by 1, 2
