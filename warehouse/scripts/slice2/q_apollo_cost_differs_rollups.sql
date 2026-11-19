-- The Apollo issuer rollups whose fair value equals the sum of the rows below them and whose cost does not
-- (int_role_subtotal near_miss_reason = 'cost_differs'): the 120 contexts (6.59bn) of Task 3 fix round 1, owner
-- decision (e). Owner decision D12 makes them subtotals through Apollo's fund rule subtotal_on_fair_value (wrapper copy
-- warehouse/wrappers/0001837532.json, reading_rules); role and rule now shown beside each. production_rows: rows
-- production has on the same accession and context (any basis).
select cf.cik, cf.instant_date as report_date, st.accession, st.context_id, cf.identifier_label
    , cf.fair_value, st.child_fair_value, cf.cost, st.child_cost, st.child_count
    , r.role, r.role_rule, r.rule_id
    , (select count(*) from stg_holdings h where h.accession_number = st.accession and h.src_context_id = st.context_id)
        as production_rows
from int_role_subtotal st
join int_context_feature cf using (accession, context_id)
join int_source_row r using (accession, context_id)
where cf.cik = '0001837532' and st.near_miss_reason = 'cost_differs'
order by report_date, accession, context_id
