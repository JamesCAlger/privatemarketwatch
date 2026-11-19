-- Task 6: cmp_row_set counts before (out/t6_cmp_before.parquet) and after the fund rules: per basis, fund, side and
-- cause, with production's and this layer's fair value in $bn. Paths relative to warehouse/ (run through run_sql.py).
with b as (select 'before' as state, * from read_parquet('scripts/slice2/out/t6_cmp_before.parquet'))
, a as (select 'after' as state, * from cmp_row_set)
, u as (
    select state, basis, cik, side, cause, fair_value, new_fair_value from b
    union all
    select state, basis, cik, side, cause, fair_value, new_fair_value from a
)
select basis, cik, side, coalesce(cause, '') as cause
    , count(*) filter (where state = 'before') as n_before
    , count(*) filter (where state = 'after') as n_after
    , round(sum(fair_value) filter (where state = 'after') / 1e9, 2) as prod_fv_bn_after
    , round(sum(new_fair_value) filter (where state = 'after') / 1e9, 2) as new_fv_bn_after
from u
group by all
order by 1, 2, 3, 4
