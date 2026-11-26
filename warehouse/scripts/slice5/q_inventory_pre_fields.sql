-- Slice 5 Task 2 inventory, run at 8dc29093 before the loader change: corrections per field and store family, with
-- withdrawals (value empty on a value correction).
select
    field
    , count(*) as corrections
    , count(*) filter (where store = 'row_corrections') as row_corrections
    , count(*) filter (where store = 'row_corrections_by_context') as by_context
    , count(*) filter (where store like 'wrapper:%') as wrapper
    , count(*) filter (where kind = 'value' and value = '') as withdrawals
    , string_agg(distinct kind, ',' order by kind) as kinds
from main.stg_correction
group by all
order by field
