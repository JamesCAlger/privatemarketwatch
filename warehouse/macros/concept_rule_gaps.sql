{#
  Review finding I1 (slice 2, Task 5): a fund concept rule matches the filer's own namespace by a glob, so a new
  dated namespace is read without an edit. This macro lists where that would still fail silently, so tests can fail:

    kind 'namespace_not_matched': the filer files a concept local name that one of its concept rules names, in a
      namespace that is not a FASB one (http://fasb.org/...) and that no concept rule of the same filer and local
      name matches. The fact would be ignored without a word.
    kind 'rule_matches_nothing': a concept rule that matches no filed fact of its filer (a typo cannot pass).

  rules: relation with rule_id, cik, sel_concept_namespace (glob), sel_concept_local.
  facts: relation with cik, accession, concept_namespace, concept_local (one row per filed fact or per distinct
  combination). Used by tests/concept_rule_namespace_gaps.sql (real data) and
  tests/concept_rule_namespace_gaps_fixture.sql (invented rows).
#}
{% macro concept_rule_gaps(rules, facts) %}
select
    'namespace_not_matched' as kind
    , f.cik
    , f.concept_namespace
    , f.concept_local
    , min(f.accession) as example_accession
    , cast(null as varchar) as rule_id
from {{ facts }} f
where f.concept_namespace not like 'http://fasb.org/%'
  and exists (select 1 from {{ rules }} r where r.cik = f.cik and r.sel_concept_local = f.concept_local)
  and not exists (
      select 1 from {{ rules }} r
      where r.cik = f.cik and r.sel_concept_local = f.concept_local and f.concept_namespace glob r.sel_concept_namespace
  )
group by 1, 2, 3, 4
union all
select
    'rule_matches_nothing'
    , r.cik
    , r.sel_concept_namespace
    , r.sel_concept_local
    , null
    , r.rule_id
from {{ rules }} r
where not exists (
    select 1 from {{ facts }} f
    where f.cik = r.cik and f.concept_local = r.sel_concept_local and f.concept_namespace glob r.sel_concept_namespace
)
{% endmacro %}
