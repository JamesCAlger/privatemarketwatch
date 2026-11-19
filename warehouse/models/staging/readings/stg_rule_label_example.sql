-- One row per label a fund rule's label_pattern must match (expected_match true) or must not match (false), as the
-- wrapper's reading_rules list them (slice 2 Task 6). No logic; tests/fund_rule_label_examples.sql applies them.
select
    rule_id
    , cik
    , label
    , expected_match
from {{ source('readings', 'rule_label_example') }}
