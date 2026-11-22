-- Slice 3 Task 4: principal pairs where production is empty and this layer has a value, and shares pairs where this
-- layer is empty or differs, by fund, field, the new side's action and production's index_classification and
-- asset_category (pipeline/unified_holdings.py empties principal on equity and fund index classes).
with b as (
    select c.basis, c.accession, c.context_id, c.cik from cmp_row_set c where c.side = 'both'
)
, p as (
    select h.accession_number as accession, h.src_context_id as context_id, h.principal_amount, h.shares_held
        , h.index_classification, h.asset_category, h.corrected_fields
    from stg_holdings h where h.src_context_id is not null
)
select b.cik, b.basis, n.field, n.action, n.reason, p.index_classification, p.asset_category
    , case when n.field = 'principal_amount' then 'prod principal null' else 'shares' end as what
    , count(*) n
    , count(*) filter (where p.shares_held is not null) as prod_has_shares
from b
join p on p.accession = b.accession and p.context_id = b.context_id
join int_field_normalised n on n.accession = b.accession and n.context_id = b.context_id
where (n.field = 'principal_amount' and n.value is not null and p.principal_amount is null)
   or (n.field = 'shares' and n.value is null and p.shares_held is not null)
   or (n.field = 'shares' and n.value is not null and p.shares_held is null)
group by all order by 1, 2, 3, 4, 6
limit 200
