-- Slice 3 Task 4 fix round 1: every context's role decision and its row-set comparison, to compare before and after
-- the fixes (no role or comparison row may move).
select s.accession, s.context_id, s.role, s.role_rule, s.reason, s.is_published, s.is_cash, s.rule_id
    , cf.fair_value, cf.cost, cf.has_term_fact
    , c.basis, c.side, c.cause, c.cause_detail
from int_source_row s
left join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
left join cmp_row_set c on c.accession = s.accession and c.context_id = s.context_id
