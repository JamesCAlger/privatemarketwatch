-- Spec section 5 rule 1: two equally specific matching rules are an error, not a tie-break. Any amount row left with
-- two rules at the top fails the build (ceiling 0). Measured 0 in slice 3 Task 3. The rate fields (slice 4 Task 3)
-- have their own measured ceiling: tests/baseline_int_field_rule_rate_conflict.sql (controller ruling: a fund with
-- both PIK-only readings conflicts on its PIK-only rows until the printed text is read).
select accession, context_id, field, cik, report_date, candidate_count, priority
from {{ ref('int_field_rule') }}
where resolution = 'rule_conflict'
  and (field in {{ amount_rule_fields() }} or field = 'principal_amount_usd')
