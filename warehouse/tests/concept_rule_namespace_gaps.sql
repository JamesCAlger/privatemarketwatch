-- Review finding I1: every filed fact of a fund's own concept is read by that fund's concept rule, whatever the
-- dated namespace, and every concept rule matches at least one filed fact (macro concept_rule_gaps). Replaces
-- tests/filer_concept_occurs_in_filed_layer.sql, which checked the deleted seed's exact namespaces.
with rules as (
    select rule_id, cik, sel_concept_namespace, sel_concept_local
    from {{ ref('stg_reading_rule') }}
    where action in ('concept_is_fair_value', 'concept_is_cost', 'concept_is_term_fact')
)
, facts as (
    select distinct fi.cik, f.accession, f.concept_namespace, f.concept_local
    from {{ ref('stg_filed_fact') }} f
    join {{ ref('stg_filed_filing') }} fi on fi.accession = f.accession
    where f.concept_local in (select sel_concept_local from rules)
)
{{ concept_rule_gaps('rules', 'facts') }}
