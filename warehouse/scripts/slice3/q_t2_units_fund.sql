-- Slice 3 Task 2: read rows per field, fund and unit, for units other than USD, shares and pure (published in its own column).
select r.field, r.unit, r.cik, count(*) as rows, count(*) filter (where s.is_published) as published
    , min(r.report_date) as first_date, max(r.report_date) as last_date
from int_field_read r
join int_source_row s on s.accession = r.accession and s.context_id = r.context_id
where r.status = 'read' and r.unit not in ('iso4217:USD', 'shares', 'pure')
  and r.field in ('fair_value', 'cost')
group by all
order by r.field, r.unit, r.cik
