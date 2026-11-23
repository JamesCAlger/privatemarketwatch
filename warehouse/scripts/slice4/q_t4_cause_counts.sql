-- Slice 4 Task 4: cmp_rate rows per basis, field, outcome, cause and detail (all funds together).
select basis, field, outcome, cause, cause_detail, count(*) as n
from cmp_rate
where outcome not in ('equal', 'both_empty')
group by all
order by basis, field, cause, cause_detail, outcome
