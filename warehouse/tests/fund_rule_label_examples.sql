-- A fund rule's label_pattern matches every label its wrapper lists under label_examples_match and none it lists under
-- label_examples_no_match (stg_rule_label_example), matched as int_role_fund_position matches (macro
-- label_first_segment, full match, case ignored). Also fails on a position_without_term_fact rule with no
-- must-not-match example: every label pattern carries its false-positive fixtures (slice 2 Task 6).
select e.rule_id, e.cik, e.label, e.expected_match, 'pattern disagrees with the example' as problem
from {{ ref('stg_rule_label_example') }} e
join {{ ref('stg_reading_rule') }} r on r.rule_id = e.rule_id
where regexp_full_match({{ label_first_segment('e.label') }}, r.sel_label_pattern, 'i') is distinct from e.expected_match
union all
select e.rule_id, e.cik, e.label, e.expected_match, 'example names no loaded rule with a label pattern'
from {{ ref('stg_rule_label_example') }} e
anti join {{ ref('stg_reading_rule') }} r on r.rule_id = e.rule_id and r.sel_label_pattern is not null
union all
select r.rule_id, r.cik, null, false, 'position_without_term_fact rule without a must-not-match example'
from {{ ref('stg_reading_rule') }} r
anti join {{ ref('stg_rule_label_example') }} e on e.rule_id = r.rule_id and not e.expected_match
where r.action = 'position_without_term_fact'
