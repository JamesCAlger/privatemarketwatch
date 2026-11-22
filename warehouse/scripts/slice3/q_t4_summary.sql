-- Slice 3 Task 4: cmp_amount counts per basis, field, outcome, cause and detail (all funds), with the sum of the
-- difference where numeric.
select basis, field, outcome, coalesce(cause, '-') as cause, coalesce(cause_detail, '-') as detail, count(*) n
    , sum(difference) as sum_difference
from cmp_amount
group by all
order by 1, 2, 3, 4, 5
limit 300
