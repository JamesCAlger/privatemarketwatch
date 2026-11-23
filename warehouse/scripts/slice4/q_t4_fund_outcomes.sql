-- Slice 4 Task 4: cmp_rate per basis, fund and field: rows by outcome, and open rows by cause.
select basis, cik, field
    , count(*) as rows
    , count(*) filter (where outcome = 'equal') as equal
    , count(*) filter (where outcome = 'differs') as differs
    , count(*) filter (where outcome = 'new_empty') as new_empty
    , count(*) filter (where outcome = 'production_empty') as production_empty
    , count(*) filter (where outcome = 'both_empty') as both_empty
    , count(*) filter (where cause = 'needs_correction') as needs_correction
    , count(*) filter (where cause = 'needs_store_not_loaded') as needs_store
    , count(*) filter (where cause = 'owner_review') as owner_review
    , count(*) filter (where cause = 'new_wrong') as new_wrong
    , count(*) filter (where cause = 'not_yet_explained') as not_yet_explained
from cmp_rate
group by all
order by 1, 2, 3
