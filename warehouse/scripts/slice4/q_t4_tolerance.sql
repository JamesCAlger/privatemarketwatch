-- Slice 4 Task 4: the tolerance of cmp_rate. Per rate field, the largest difference on rows called equal and the
-- smallest on rows called differs (percentage points), and how many differing rows sit below 0.005.
select field
    , count(*) filter (where outcome = 'equal') as equal_rows
    , max(abs(difference)) filter (where outcome = 'equal') as max_equal_diff
    , count(*) filter (where outcome = 'differs') as differs_rows
    , min(abs(difference)) filter (where outcome = 'differs') as min_differs_diff
    , count(*) filter (where outcome = 'differs' and abs(difference) < 0.005) as differs_below_half_bp
from cmp_rate
where field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread')
group by 1
order by 1
