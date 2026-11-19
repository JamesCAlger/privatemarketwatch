-- Task 5, review finding I1: the facts the fund concept rules (one per fund and reading, namespace glob) match,
-- against the facts the 48 rows of the deleted seed filer_concept.csv matched (40 at fix round 3 plus 8 bo_commit_term
-- rows in 3b; exact namespaces). The seed is read from the table filer_concept that stays in the local
-- warehouse.duckdb (dbt does not drop a deleted seed's table). Measured 2026-11-19: 0 facts on either side only.
with seed as (
    select cik, concept_namespace, concept_local, maps_to from filer_concept
)
, rules as (
    select cik, sel_concept_namespace, sel_concept_local
        , case action when 'concept_is_fair_value' then 'fair_value' else 'term_fact' end as maps_to
    from stg_reading_rule where action in ('concept_is_fair_value', 'concept_is_term_fact')
)
, facts as (
    select fi.cik, f.accession, f.context_id, f.fact_id, f.concept_namespace, f.concept_local
    from stg_filed_fact f join stg_filed_filing fi on fi.accession = f.accession
    where f.concept_local in (select concept_local from seed)
)
, by_seed as (
    select distinct f.fact_id, f.accession, s.maps_to from facts f
    join seed s on s.cik = f.cik and s.concept_namespace = f.concept_namespace and s.concept_local = f.concept_local
)
, by_rule as (
    select distinct f.fact_id, f.accession, r.maps_to from facts f
    join rules r on r.cik = f.cik and f.concept_namespace glob r.sel_concept_namespace and r.sel_concept_local = f.concept_local
)
select 'seed rows' k, null as maps_to, count(*) n from seed
union all select 'rules', null, count(*) from rules
union all select 'facts by seed', maps_to, count(*) from by_seed group by 2
union all select 'facts by rule', maps_to, count(*) from by_rule group by 2
union all select 'seed only', maps_to, count(*) from (select * from by_seed except select * from by_rule) group by 2
union all select 'rule only', maps_to, count(*) from (select * from by_rule except select * from by_seed) group by 2
order by 1, 2
