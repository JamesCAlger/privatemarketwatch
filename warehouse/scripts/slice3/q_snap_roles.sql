-- Slice 3 Task 1: row-level snapshot of int_source_row (exported with slice2/export_query.py).
select accession, context_id, cik, report_date, role, role_rule, rule_id, reason, scope, is_cash, is_published
    , cross_check_agrees, cash_rule_id, cash_pattern_id, concept_rule_id, position_rule_id
from int_source_row
