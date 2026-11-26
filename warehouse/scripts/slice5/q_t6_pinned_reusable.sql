-- Slice 5 Task 6, consolidation measure (a), part 1: loaded corrections (stg_correction) per fund, store, kind and
-- field, pinned or reusable. Measure only.
-- Pinned: the correction names one filing (accession) and one row in it (context id or identifier text), or names
-- one production row id (agent B2 leaf). Reusable: it names no row (no such correction can be loaded today: every
-- store the loader reads is keyed by row; the count proves it).
select
    cik
    , store
    , kind
    , field
    , count(*) as corrections
    , count(*) filter (
        where (accession is not null and (context_id is not null or identifier is not null)) or row_id is not null
      ) as pinned
    , count(*) filter (
        where not ((accession is not null and (context_id is not null or identifier is not null)) or row_id is not null)
      ) as reusable
    , count(*) filter (where context_id is not null) as by_context
    , count(*) filter (where context_id is null and identifier is not null) as by_identifier
    , count(*) filter (where row_id is not null) as by_row_id
from main.stg_correction
group by all
order by cik, store, kind, field
