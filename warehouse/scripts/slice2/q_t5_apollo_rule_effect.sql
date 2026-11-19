-- Task 5, owner decision D12: every context whose role changed when the Apollo fund rule subtotal_on_fair_value was
-- switched on (before: out/t5_roles_moved.parquet, the moved state without the rule in force; after: now). For each:
-- label, fair value, the rule 6 test, the term facts it carries, and whether production publishes it. Owner test
-- ("does not affect real rows"): no changed row may be published by production, none may carry a rate, spread, PIK
-- rate or maturity, and no row may change outside Apollo.
with b as (select * from read_parquet('scripts/slice2/out/t5_roles_moved.parquet'))
, a as (select * from int_source_row)
, changed as (
    select a.accession, a.context_id, a.cik, a.report_date, b.role as role_before, b.role_rule as rule_before
        , a.role as role_after, a.role_rule as rule_after, a.rule_id, a.reason
    from b join a using (accession, context_id)
    where b.role is distinct from a.role or b.role_rule is distinct from a.role_rule or b.is_published <> a.is_published
)
, prod as (
    select accession_number as accession, src_context_id as context_id
        , bool_or(accounting_record_class is distinct from 'underlying_schedule') as prod_published
        , count(*) as prod_rows
    from stg_holdings group by 1, 2
)
select c.cik, c.report_date, c.accession, c.context_id, cf.identifier_label
    , c.role_before || ' r' || c.rule_before as before, c.role_after || ' r' || c.rule_after as after
    , cf.fair_value, cf.cost, st.child_count, st.child_fair_value, st.child_cost, st.near_miss_reason
    , cf.has_rate or cf.has_spread or cf.has_pik_rate or cf.has_maturity as guard_terms
    , cf.has_principal, cf.has_shares
    , coalesce(p.prod_published, false) as production_publishes, coalesce(p.prod_rows, 0) as production_rows
    , c.rule_id
from changed c
join int_context_feature cf using (accession, context_id)
left join int_role_subtotal st using (accession, context_id)
left join prod p using (accession, context_id)
order by c.cik, c.report_date, c.accession, c.context_id
