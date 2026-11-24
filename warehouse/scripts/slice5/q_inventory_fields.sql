-- Slice 5 Task 2 inventory (A3): loaded corrections per field and store, with withdrawals (empty value) and the
-- correction_field seed row the field maps to (null when the seed lacks it).
select
    c.field
    , c.store
    , count(*) as corrections
    , count(*) filter (where c.kind = 'value' and c.value = '') as withdrawals
    , string_agg(distinct c.kind, ',' order by c.kind) as kinds
    , any_value(f.step) as step
    , any_value(f.layer_field) as layer_field
from main.stg_correction c
left join main.correction_field f
    on f.correction_field = c.field and regexp_full_match(c.store, f.store_pattern)
group by all
order by c.field, c.store
