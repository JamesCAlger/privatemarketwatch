-- Every rule_id and cash_rule_id given names a row of seeds/role_pattern.csv or of the rule table (stg_reading_rule);
-- every concept_rule_id names a concept rule (concept_is_fair_value, concept_is_term_fact) of the rule table for the
-- same filer.
-- Anti joins, not NOT IN: a null on the right side of NOT IN would make the test pass without checking.
with given as (
    select accession, context_id, rule_id as id, 'rule_id' as col from {{ ref('int_source_row') }} where rule_id is not null
    union all
    select accession, context_id, cash_rule_id, 'cash_rule_id' from {{ ref('int_source_row') }} where cash_rule_id is not null
)
select g.accession, g.context_id, g.id, g.col
from given g
anti join {{ ref('role_pattern') }} p on p.pattern_id = g.id
anti join {{ ref('stg_reading_rule') }} r on r.rule_id = g.id
union all
select s.accession, s.context_id, s.concept_rule_id, 'concept_rule_id'
from {{ ref('int_source_row') }} s
anti join {{ ref('stg_reading_rule') }} r
    on r.rule_id = s.concept_rule_id and r.cik = s.cik and r.action in ('concept_is_fair_value', 'concept_is_term_fact')
where s.concept_rule_id is not null
union all
-- every position_rule_id names a position_without_term_fact rule of the same filer (slice 2 Task 6)
select s.accession, s.context_id, s.position_rule_id, 'position_rule_id'
from {{ ref('int_source_row') }} s
anti join {{ ref('stg_reading_rule') }} r
    on r.rule_id = s.position_rule_id and r.cik = s.cik and r.action = 'position_without_term_fact'
where s.position_rule_id is not null
