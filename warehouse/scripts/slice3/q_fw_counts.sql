-- Slice 3 final fix wave: cmp_amount open rows by basis, field, cause and detail (read-only).
select basis, field, cause, cause_detail, count(*) as n
from cmp_amount
where cause is not null
group by all
order by 1, 2, 3, 4
limit 400
