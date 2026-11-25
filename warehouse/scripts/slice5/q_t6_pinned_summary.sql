-- Slice 5 Task 6, consolidation measure (a), part 2: the same as q_t6_pinned_reusable.sql summed per fund, store and
-- kind (field rolled up). Measure only.
select
    cik
    , store
    , kind
    , count(distinct field) as fields
    , count(*) as corrections
    , count(*) filter (
        where (accession is not null and (context_id is not null or identifier is not null)) or row_id is not null
      ) as pinned
    , count(*) filter (
        where not ((accession is not null and (context_id is not null or identifier is not null)) or row_id is not null)
      ) as reusable
    , count(distinct accession) as filings
    , count(distinct add_group_id) as add_groups
from main.stg_correction
group by all
order by cik, store, kind
