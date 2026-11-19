-- Concepts on investment-identifier contexts, by namespace and fund: how many facts.
with idctx as (
    select distinct accession, context_id
    from stg_filed_context_member
    where axis like '%:InvestmentIdentifierAxis'
)
select f.concept_local, regexp_replace(f.concept_namespace, '/20[0-9]{2}.*$', '') as ns
    , count(*) as facts
    , count(distinct fi.cik) as funds
    , count(*) filter (where f.unit_id is not null) as numeric_facts
from stg_filed_fact f
join idctx using (accession, context_id)
join stg_filed_filing fi using (accession)
group by 1, 2
order by facts desc
