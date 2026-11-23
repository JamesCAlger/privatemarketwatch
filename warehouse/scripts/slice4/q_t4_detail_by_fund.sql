-- Slice 4 Task 4: cmp_rate open rows per cause detail and fund (both bases).
select cause_detail, cik, count(*) as n
from cmp_rate
where cause is not null
group by all
order by 1, 2
