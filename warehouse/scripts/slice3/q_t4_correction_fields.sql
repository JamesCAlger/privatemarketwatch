-- Slice 3 Task 4 (exploration): loaded corrections for the five funds by store, kind and field, and how many carry a
-- context id.
select cik, store, kind, field, count(*) n, count(context_id) with_context, count(identifier) with_identifier
from stg_correction
group by all order by 1, 2, 3, 4
limit 200
