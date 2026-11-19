-- Task 6: per basis and fund, rows and fair value ($bn) on both sides, new only and production only, for the baseline
-- document's tables (fund rows then a total row per basis).
select basis, coalesce(cik, 'total') as cik
    , count(*) filter (where side = 'both') as both_n
    , round(sum(fair_value) filter (where side = 'both') / 1e9, 2) as both_prod_bn
    , round(sum(new_fair_value) filter (where side = 'both') / 1e9, 2) as both_new_bn
    , count(*) filter (where side = 'new_only') as new_only_n
    , round(sum(new_fair_value) filter (where side = 'new_only') / 1e9, 3) as new_only_bn
    , count(*) filter (where side = 'production_only') as prod_only_n
    , round(sum(fair_value) filter (where side = 'production_only') / 1e9, 3) as prod_only_prod_bn
    , round(sum(new_fair_value) filter (where side = 'production_only') / 1e9, 3) as prod_only_new_bn
from cmp_row_set
group by grouping sets ((basis, cik), (basis))
order by basis, cik
