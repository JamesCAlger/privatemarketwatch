-- Slice 5 Task 2 inventory: loaded corrections by kind and seed step (correction_field), per store family; withdrawals
-- (empty value on a value correction) counted apart. Re-measures appendix A3 on the seed's steps.
select
    c.kind
    , f.step
    , count(*) as corrections
    , count(*) filter (where c.store in ('row_corrections')) as row_corrections
    , count(*) filter (where c.store in ('row_corrections_by_context')) as by_context
    , count(*) filter (where c.store like 'wrapper:%') as wrapper
    , count(*) filter (where c.store like 'agent_%') as agent
    , count(*) filter (where c.kind = 'value' and c.value = '') as withdrawals
from main.stg_correction c
left join main.correction_field f
    on f.correction_field = c.field and regexp_full_match(c.store, f.store_pattern)
group by all
order by 1, 2
