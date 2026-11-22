-- Slice 3 Task 3: int_field_normalised counts per fund, field, action, status and reason (all positions; published in
-- its own column).
select n.cik, n.field, coalesce(n.action, '-') as action_name, n.status, n.reason, count(*) n_all
    , count(*) filter (where s.is_published) n_published
from int_field_normalised n
join int_source_row s on s.accession = n.accession and s.context_id = n.context_id
group by all order by 1, 2, 3, 4, 5
limit 400
