-- The I1 check itself, on invented rows (macro concept_rule_gaps). Fund 1 has a concept rule for its own domain with a
-- dated glob: its 2025 and 2026 namespaces are read; the same local name in another domain of its own
-- (http://other.example/2026) is NOT matched and must be listed; the FASB namespace is never listed; fund 2 files the
-- same local name and has no rule, so it is not listed. A rule that matches no fact (fund 3) must be listed.
-- Returns a row for every expectation that does not hold.
with rules as (
    select * from (values
          ('r1', '1', 'http://filer.example/*', 'OwnConcept')
        , ('r3', '3', 'http://three.example/*', 'NeverFiled')
    ) v(rule_id, cik, sel_concept_namespace, sel_concept_local)
)
, facts as (
    select * from (values
          ('1', 'A1', 'http://filer.example/20250331', 'OwnConcept')
        , ('1', 'A2', 'http://filer.example/20260331', 'OwnConcept')
        , ('1', 'A3', 'http://other.example/2026', 'OwnConcept')
        , ('1', 'A3', 'http://fasb.org/us-gaap/2025', 'OwnConcept')
        , ('2', 'B1', 'http://two.example/2026', 'OwnConcept')
        , ('3', 'C1', 'http://three.example/2026', 'OtherConcept')
    ) v(cik, accession, concept_namespace, concept_local)
)
, got as (
    {{ concept_rule_gaps('rules', 'facts') }}
)
, expected as (
    select * from (values
          ('namespace_not_matched', '1', 'http://other.example/2026')
        , ('rule_matches_nothing', '3', 'http://three.example/*')
    ) v(kind, cik, concept_namespace)
)
select 'missing' as problem, e.* from expected e
anti join got g on g.kind = e.kind and g.cik = e.cik and g.concept_namespace = e.concept_namespace
union all
select 'unexpected', g.kind, g.cik, g.concept_namespace from got g
anti join expected e on g.kind = e.kind and g.cik = e.cik and g.concept_namespace = e.concept_namespace
