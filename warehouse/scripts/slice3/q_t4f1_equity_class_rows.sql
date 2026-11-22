-- Slice 3 Task 4 fix round 1: the principal pairs where production holds no principal and no dollar principal but
-- kept the currency, and this layer read the principal as filed, with production's class columns and text, grouped by
-- production's index class (item 1: which carry an equity or fund class).
select a.cik, a.basis, h.index_classification, h.asset_category, h.asset_class, count(*) n
    , min(left(h.issuer_name, 40)) as an_issuer, max(left(h.issuer_name, 40)) as another_issuer
    , min(left(h.extracted_industry, 40)) as an_industry, min(left(h.corrected_fields, 60)) as a_corrected
from cmp_amount a
join stg_holdings h on h.accession_number = a.accession and h.src_context_id = a.context_id
where a.field = 'principal_amount' and a.outcome = 'production_empty' and a.new_action = 'as_filed'
  and h.principal_amount is null and h.principal_amount_usd is null and h.principal_amount_currency is not null
group by all order by 1, 2, 3
limit 50
