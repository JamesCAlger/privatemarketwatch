-- Task 5, D12: the 140 changed rows of q_t5_apollo_rule_effect.sql split by the rule 6 test that failed, the guard
-- terms, principal/shares, production rows (any basis) and quarter range.
with e as (
    select * from read_csv('scripts/slice2/out/t5_apollo_rule_effect.csv', header = true, all_varchar = true)
)
select near_miss_reason, guard_terms, has_principal, has_shares, production_publishes, production_rows
    , count(*) n, min(report_date) first_q, max(report_date) last_q, round(sum(fair_value::double) / 1e9, 3) as fv_bn
from e group by all order by 1, 2
