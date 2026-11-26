-- Slice 5 Task 5: counts per comparison model, basis, field, cause and detail (outcomes other than equal and
-- both_empty, and one-sided rows of cmp_row_set). Run before and after the task. Read-only.
select 'cmp_amount' as model, basis, field, cause, cause_detail, count(*) as n
from cmp_amount where cause is not null group by all
union all
select 'cmp_rate', basis, field, cause, cause_detail, count(*)
from cmp_rate where cause is not null group by all
union all
select 'cmp_row_set', basis, side, cause, cause_detail, count(*)
from cmp_row_set where cause is not null group by all
order by 1, 2, 3, 4, 5
