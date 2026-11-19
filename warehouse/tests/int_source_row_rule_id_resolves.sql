-- Every rule_id and cash_rule_id given names a row of seeds/role_pattern.csv or of the rule table (stg_reading_rule).
-- Anti joins, not NOT IN: a null on the right side of NOT IN would make the test pass without checking.
with given as (
    select accession, context_id, rule_id as id, 'rule_id' as col from {{ ref('int_source_row') }} where rule_id is not null
    union all
    select accession, context_id, cash_rule_id, 'cash_rule_id' from {{ ref('int_source_row') }} where cash_rule_id is not null
)
select g.*
from given g
anti join {{ ref('role_pattern') }} p on p.pattern_id = g.id
anti join {{ ref('stg_reading_rule') }} r on r.rule_id = g.id
