-- Task 6: where Blue Owl and HPS tag a us-gaap commitment concept, and what counting it as a term fact would touch.
-- Every context of the fund carrying the concept, by current role and term fact, and production's handling.
with p as (
    select accession_number as accession, src_context_id as context_id
        , bool_or(accounting_record_class is distinct from 'underlying_schedule') as published
        , bool_or(accounting_record_class = 'underlying_schedule') as jv
    from stg_holdings group by 1, 2
)
, c as (
    select distinct fi.cik, f.accession, f.context_id, f.concept_local
    from stg_filed_fact f join stg_filed_filing fi using (accession)
    where fi.cik in ('0001812554', '0001838126')
      and f.concept_namespace like 'http://fasb.org/us-gaap/%'
      and f.concept_local in ('QualifiedAffordableHousingProjectInvestmentsCommitment'
          , 'InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount'
          , 'InvestmentCompanyFinancialSupportToInvesteeContractuallyRequiredAmount')
)
select c.cik, c.concept_local, r.role, r.role_rule, cf.has_term_fact, r.scope
    , case when p.published then 'publishes' when p.jv then 'jv' else 'none' end as production
    , count(*) as n
from c
join int_source_row r using (accession, context_id)
join int_context_feature cf using (accession, context_id)
left join p using (accession, context_id)
group by all
order by all
