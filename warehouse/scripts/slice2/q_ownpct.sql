-- Fix round 2 A: contexts carrying InvestmentOwnedBalancePercentOfShares, by namespace kind, current role and rule.
with f as (
  select accession, context_id
    , bool_or(concept_namespace like 'http://fasb.org/us-gaap/%' or concept_namespace like 'http://fasb.org/us-gaap-sup/%') as fasb
    , min(concept_namespace) as ns
  from stg_filed_fact
  where concept_local = 'InvestmentOwnedBalancePercentOfShares'
  group by 1, 2
)
select r.cik, f.fasb, regexp_replace(f.ns, '/[0-9]+$', '') as ns, r.role, r.role_rule, count(*) n
from int_source_row r join f on f.accession = r.accession and f.context_id = r.context_id
group by all order by 1, 2, 3, 4, 5
