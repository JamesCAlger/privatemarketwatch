-- Slice 3 Task 4: headline counts of cmp_amount per basis and field, by outcome, with the row total (each must equal
-- the rows on both sides of that basis) and not_yet_explained.
select basis, field
    , count(*) filter (where outcome = 'equal') as equal
    , count(*) filter (where outcome = 'differs') as differs
    , count(*) filter (where outcome = 'new_empty') as new_empty
    , count(*) filter (where outcome = 'production_empty') as production_empty
    , count(*) filter (where outcome = 'both_empty') as both_empty
    , count(*) as total
    , count(*) filter (where cause = 'not_yet_explained') as not_yet_explained
from cmp_amount
group by all order by 1, 2
