-- Slice 3 Task 4: cmp_amount outcomes per field and this layer's action (published and JV bases together), to see how
-- each Task 3 action compares with production.
select field, coalesce(new_action, '-') as new_action, outcome, coalesce(cause_detail, '-') as detail, count(*) n
from cmp_amount
where new_action is not null and new_action <> 'as_filed'
group by all order by 1, 2, 3, 4
limit 100
