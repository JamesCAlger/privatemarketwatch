-- Task 6: the 133 owner-review rows (docs/owner_review_rows_2026-11-19.csv) with the fund rule that now releases each
-- (position_without_term_fact, or a concept_is_term_fact rule supplying the term fact; empty where none) and the row's
-- role now. Writes the CSV's columns in their order plus release_rule_id, release_action, role_now.
with o as (
    select * from read_csv('docs/owner_review_rows_2026-11-19.csv', all_varchar = true, header = true)
)
, r as (
    select s.accession, s.context_id, s.role
        , coalesce(s.position_rule_id, case when cf.term_fact_source <> 'standard' then cf.term_fact_source end) as rule_id
    from int_source_row s join int_context_feature cf using (accession, context_id)
)
select o.cik, o.report_date, o.accession, o.context_id, o.label, o.fair_value, o.class, o.basis, o.cause
    , coalesce(r.rule_id, '') as release_rule_id
    , coalesce(rr.action, '') as release_action
    , r.role as role_now
from o
left join r using (accession, context_id)
left join stg_reading_rule rr on rr.rule_id = r.rule_id
order by o.cik, o.class, o.label, o.report_date, o.context_id
