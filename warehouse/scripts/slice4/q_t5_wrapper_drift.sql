-- Slice 4 Task 5 repair (a): the wrapper-drift view after the change to text hashes (CRLF read as LF). One row per
-- fund: production side (changed) and copy side (copy_changed), with the first 12 characters of each hash.
select cik, changed, copy_changed
    , left(copied_sha256, 12) as copied
    , left(current_sha256, 12) as current_production
    , left(loaded_copy_sha256, 12) as loaded_copy
    , left(copy_sha256, 12) as copy_now
from stg_wrapper_drift
order by 1
