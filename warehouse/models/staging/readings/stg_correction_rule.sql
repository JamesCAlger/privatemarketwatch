-- One row per row-selecting rule of the two agent stores (slice 5 Task 2, decision 1): an investigator row_exclusion
-- (its predicate_sql, written in production's column names) or a B2 comparative_period_filter (its template, JSON).
-- Loaded for the record only; no model applies it. This layer's row roles reproduce what these rules remove (the row
-- sets agree, slice 5 plan); a rule that does not is seen in cmp_row_set. Empty text becomes null.
select
    rule_row_id
    , cik
    , store
    , rule_id
    , rule_type
    , nullif(action, '') as action
    , nullif(scope_quarters, '') as scope_quarters
    , predicate
    , predicate_form
    , nullif(evidence, '') as evidence
    , nullif(reason, '') as reason
    , source_file
from {{ source('readings', 'correction_rule') }}
