-- Slice 4 Task 3: per fund and rate field, rows by status, reason and action (all position rows; published beside).
select n.cik, n.field, n.status, n.reason, n.action, coalesce(n.rate_kind, '') as rate_kind
    , count(*) as n, count(*) filter (where s.is_published) as published
from int_field_normalised n
join int_source_row s on s.accession = n.accession and s.context_id = n.context_id
where n.field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
group by all
order by 1, 2, 3, 4, 5
