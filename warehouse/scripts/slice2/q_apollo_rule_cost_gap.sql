-- For the owner (slice 2 Task 5 fix round 1): rollups that Apollo's fund rule subtotal_on_fair_value makes
-- subtotals (int_role_subtotal.subtotal_rule_id) whose own cost differs from the summed cost of the rows directly
-- beneath by more than 10 percent of that summed cost. Fair value ties exactly within rule 6's tolerance on every row.
-- A large cost gap with a fair-value tie may mean a position beneath the rollup that carries cost and no fair value
-- and is not tagged. Rows whose cost cannot be compared (cost_not_comparable) have no gap to measure and are not
-- listed. Costs and fair values in $m.
select cf.instant_date as report_date, st.accession, st.context_id, cf.identifier_label
    , round(cf.cost / 1e6, 3) as rollup_cost_m, round(st.child_cost / 1e6, 3) as rows_beneath_cost_m
    , round((cf.cost - st.child_cost) / 1e6, 3) as cost_gap_m
    , round(100 * (cf.cost - st.child_cost) / nullif(abs(st.child_cost), 0), 1) as gap_pct_of_beneath
    , round(cf.fair_value / 1e6, 3) as rollup_fv_m, round(st.child_fair_value / 1e6, 3) as rows_beneath_fv_m
    , st.child_count
from int_role_subtotal st
join int_context_feature cf using (accession, context_id)
where st.subtotal_rule_id is not null
  and st.near_miss_reason = 'cost_differs'
  and abs(cf.cost - st.child_cost) > 0.10 * abs(st.child_cost)
order by report_date, identifier_label
