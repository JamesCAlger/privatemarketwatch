-- Slice 3 Task 4: facts on position contexts of the five funds whose local name contains one of production's amount
-- substrings (pipeline/bdc_filings.py CONCEPT_MAP, matched as substrings of the lowercased local name, any namespace)
-- but that no concept_map row reads (local name and namespace glob). Grouped by namespace host, local name and the
-- production field the substring maps to.
with pat as (
    select * from (values
        ('investmentownedatfairvalue', 'fair_value'), ('investmentownedfairvalue', 'fair_value'),
        ('moneymarketfundsatfairvalue', 'fair_value'),
        ('investmentownedatcost', 'cost'), ('investmentownedcost', 'cost'), ('moneymarketfundsatcarryingvalue', 'cost'),
        ('investmentownedbalanceprincipalamount', 'principal_amount'),
        ('investmentownedbalancesharesornumberofcontractsorprincipalamount', 'principal_amount'),
        ('investmentownedunderlyingfaceamountatmarketvalue', 'principal_amount'),
        ('investmentownedbalanceshares', 'shares_held'), ('investmentownednumberofsharesornumberofcontracts', 'shares_held')
    ) v(pattern, prod_field)
)
, pos as (
    select accession, context_id, cik from int_source_row where role = 'position'
)
, f as (
    select p.cik, f.accession, f.context_id, f.concept_namespace, f.concept_local
    from stg_filed_fact f
    join pos p on p.accession = f.accession and p.context_id = f.context_id
    where f.value_numeric is not null
)
, matched as (
    select f.*, (select min_by(prod_field, -length(pattern)) from pat where contains(lower(f.concept_local), pattern)) as prod_field
    from f
)
select cik, regexp_extract(concept_namespace, '^https?://([^/]+)', 1) as host, concept_local, prod_field
    , count(*) n_facts, count(distinct accession) n_filings
from matched m
where prod_field is not null
  and not exists (select 1 from concept_map c where c.concept_local = m.concept_local and m.concept_namespace glob c.namespace_pattern)
group by all order by 1, 2, 3
limit 100
