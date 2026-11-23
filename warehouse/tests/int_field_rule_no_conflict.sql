-- Spec section 5 rule 1: two equally specific matching rules are an error, not a tie-break. Any amount row left with
-- two rules at the top fails the build (ceiling 0). Measured 0 in slice 3 Task 3. The rate fields (slice 4 Task 3)
-- have their own guard: tests/baseline_int_field_rule_rate_conflict.sql, ceiling 0 (since the controller ruling of
-- 2026-11-23 the PIK-only rows of a fund with both readings are text_not_read, not a conflict).
select accession, context_id, field, cik, report_date, candidate_count, priority
from {{ ref('int_field_rule') }}
where resolution = 'rule_conflict'
  and (field in {{ amount_rule_fields() }} or field = 'principal_amount_usd')
