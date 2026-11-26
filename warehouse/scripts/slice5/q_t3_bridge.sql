-- Slice 5 Task 3 proof: the production_bridge (owner decision 2, a named debt): corrections by fund, field outcome and
-- the role the bridged context had, and the ambiguous one.
select a.cik, a.outcome, coalesce(a.reason, '') as reason, a.target_role, count(*) as corrections
    , string_agg(distinct a.field, ', ' order by a.field) as fields
from main.int_correction_application a
where a.key_resolution = 'production_bridge'
group by all
order by 1, 2, 3, 4
