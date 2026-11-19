-- Final fix wave: snapshot of every context's role and cash flag, for the before/after comparison (q_ff_roles_moved.sql).
select r.accession, r.context_id, r.cik, r.report_date, r.role, r.role_rule, r.rule_id, r.is_cash, r.is_published
    , cf.identifier_label, cf.fair_value
from int_source_row r
join int_context_feature cf using (accession, context_id)
