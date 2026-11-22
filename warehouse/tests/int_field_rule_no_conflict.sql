-- Spec section 5 rule 1: two equally specific matching rules are an error, not a tie-break. Any row left with two
-- rules at the top fails the build (ceiling 0). Measured 0 in slice 3 Task 3.
select accession, context_id, field, cik, report_date, candidate_count, priority
from {{ ref('int_field_rule') }}
where resolution = 'rule_conflict'
