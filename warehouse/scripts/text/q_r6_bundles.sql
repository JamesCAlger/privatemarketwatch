-- Slice R phase 1 (2026-11-26): bundle counts and sizes per fund and worklist state, and one sample. Read-only.
select cik, worklist_state, count(*) as bundles, min(bundle_chars) as min_chars, max(bundle_chars) as max_chars
    , sum(bundle_chars) as total_chars
from int_text_bundle group by all order by 1, 2
