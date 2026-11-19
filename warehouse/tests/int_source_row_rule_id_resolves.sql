-- Every rule_id and cash_rule_id given names a row of seeds/role_pattern.csv or of the rule table (stg_reading_rule);
-- every filer_concept_id names a row of seeds/filer_concept.csv for the same filer.
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
select s.accession, s.context_id, s.filer_concept_id, 'filer_concept_id'
from {{ ref('int_source_row') }} s
anti join {{ ref('filer_concept') }} fc on fc.filer_concept_id = s.filer_concept_id and fc.cik = s.cik
where s.filer_concept_id is not null
