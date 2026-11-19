-- Filings that use a FASB supplement namespace for term concepts on identifier contexts.
with idctx as (
    select distinct accession, context_id
    from stg_filed_context_member
    where axis like '%:InvestmentIdentifierAxis'
)
select fi.cik, fi.document_period_end_date, f.accession, f.concept_namespace, f.concept_local, count(*) as facts
from stg_filed_fact f
join idctx using (accession, context_id)
join stg_filed_filing fi using (accession)
where f.concept_namespace not like 'http://fasb.org/us-gaap/%'
  and f.concept_namespace like 'http://fasb.org/%'
group by all
order by 2, 1, 5
