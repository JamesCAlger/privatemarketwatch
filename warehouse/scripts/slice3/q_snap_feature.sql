-- Slice 3 Task 1: row-level snapshot of the int_context_feature columns that existed before the concept map
-- (exported with slice2/export_query.py). The new column fair_value_rule_id is not in it.
select accession, context_id, cik, instant_date, period_type, member_count, has_identifier_member, identifier_label
    , other_axes, other_members, is_filing_period_end, fair_value, fair_value_source, fair_value_filer_concept_also_present
    , cost, fair_value_fact_count, cost_fact_count, has_principal, has_shares, has_rate, has_spread, has_pik_rate
    , has_maturity, has_ownership_percent, has_term_fact, term_fact_source
from int_context_feature
