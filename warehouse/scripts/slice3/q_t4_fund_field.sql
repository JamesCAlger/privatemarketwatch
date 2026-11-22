-- Slice 3 Task 4: cmp_amount counts per fund, basis and field by outcome, and the open rows by cause.
select cik, basis, field
    , count(*) filter (where outcome = 'equal') as equal
    , count(*) filter (where outcome = 'differs') as differs
    , count(*) filter (where outcome = 'new_empty') as new_empty
    , count(*) filter (where outcome = 'production_empty') as production_empty
    , count(*) filter (where outcome = 'both_empty') as both_empty
    , count(*) filter (where cause = 'needs_correction') as needs_correction
    , count(*) filter (where cause = 'new_wrong') as new_wrong
    , count(*) filter (where cause = 'convention') as convention
    , count(*) filter (where cause = 'owner_review') as owner_review
    , count(*) filter (where cause = 'old_wrong') as old_wrong
    , count(*) filter (where cause = 'not_yet_explained') as not_yet_explained
from cmp_amount
group by all order by 1, 2, 3
limit 100
