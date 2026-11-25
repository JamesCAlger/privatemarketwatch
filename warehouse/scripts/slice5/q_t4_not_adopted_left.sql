-- Slice 5 Task 4 (review minor 1): the cmp_rate rows still carrying rate_only_context_not_adopted. Read-only.
select accession, context_id, field, outcome, value_new, value_production, text_new, text_production, new_reason
from cmp_rate where cause_detail = 'rate_only_context_not_adopted' order by 1, 2, 3
