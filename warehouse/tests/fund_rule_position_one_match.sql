-- No context is matched by two fund rules position_without_term_fact (spec section 5: two equal matches are an
-- error, not a tie-break). int_source_row leaves such a row unresolved; this test makes the overlap fail the build.
-- Label patterns cannot be compared statically, so overlap is measured on the filed rows (tests/fund_rule_no_overlap.sql
-- covers the concept and subtotal actions).
select accession, context_id, match_count
from {{ ref('int_role_fund_position') }}
where match_count > 1
