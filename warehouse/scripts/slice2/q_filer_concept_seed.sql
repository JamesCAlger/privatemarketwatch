-- Fix round 3: generate the filer_concept seed lines from the filed layer (one per filer, namespace, concept), with
-- evidence counts: facts, contexts, of which with an investment identifier member, of which also with a standard FV fact.
with f as (
  select fi.cik, f.accession, f.context_id, f.concept_namespace, f.concept_local
  from stg_filed_fact f join stg_filed_filing fi on fi.accession = f.accession
  where (fi.cik = '0001287750' and f.concept_local = 'InvestmentOwnedBalancePercentOfShares')
     or (fi.cik = '0001812554' and f.concept_local = 'InvestmentOwnedFairValueNetOfUnamortizedFees')
     or (fi.cik = '0001837532' and f.concept_local = 'InvestmentOwnedAtFairValueAfterCashEquivalents')
), g as (
  select f.cik, f.concept_namespace, f.concept_local, min(f.accession) acc, count(*) facts
    , count(distinct f.context_id) ctx
    , count(distinct f.context_id) filter (where cf.has_identifier_member) ctx_ident
    , count(distinct f.context_id) filter (where cf.fair_value_fact_count > 0) ctx_std_fv
  from f join int_context_feature cf on cf.accession = f.accession and cf.context_id = f.context_id
  group by all
)
select
  case cik when '0001287750' then 'ares_pct_shares_' when '0001812554' then 'bo_fv_net_fees_' else 'apollo_fv_cash_eq_' end
    || regexp_extract(concept_namespace, '([0-9]{8})$', 1) || ','
  || cik || ',' || concept_namespace || ',' || concept_local || ','
  || case cik when '0001287750' then 'term_fact' else 'fair_value' end || ','
  || '"' || case cik
       when '0001287750' then 'Ares own concept: percent of the issuer shares or units held, tagged on partnership member and LLC interest lines that carry no other term fact'
       when '0001812554' then 'Blue Owl own concept: fair value net of unamortized fees, the only fair-value tag on its unfunded commitment lines'
       else 'Apollo own concept: fair value of its cash equivalents (money-market funds) on the cash axis, tagged instead of InvestmentOwnedAtFairValue' end || '",'
  || '"' || acc || ': ' || facts || ' facts on ' || ctx || ' contexts, ' || ctx_ident || ' with an investment identifier member, '
  || ctx_std_fv || ' also carrying the us-gaap fair-value fact"' as line
from g order by cik, concept_namespace
