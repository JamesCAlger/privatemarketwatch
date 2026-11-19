-- Every rule_id and cash_rule_id given names a row of seeds/role_pattern.csv or of the rule table (stg_reading_rule).
with given as (
    select accession, context_id, rule_id as id, 'rule_id' as col from {{ ref('int_source_row') }} where rule_id is not null
    union all
    select accession, context_id, cash_rule_id, 'cash_rule_id' from {{ ref('int_source_row') }} where cash_rule_id is not null
)
select g.*
from given g
where g.id not in (select pattern_id from {{ ref('role_pattern') }})
  and g.id not in (select rule_id from {{ ref('stg_reading_rule') }})
