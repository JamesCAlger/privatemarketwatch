-- Slice 3 Task 4: principal currency, this layer against production's principal_amount_currency, on rows both sides
-- have, grouped by outcome and whether each side's principal is present.
with b as (
    select c.basis, c.accession, c.context_id, c.cik from cmp_row_set c where c.side = 'both'
)
select b.cik, b.basis
    , n.currency as cur_new, h.principal_amount_currency as cur_prod
    , n.value is not null as new_principal, h.principal_amount is not null as prod_principal
    , n.action
    , count(*) n
from b
join stg_holdings h on h.accession_number = b.accession and h.src_context_id = b.context_id
join int_field_normalised n on n.accession = b.accession and n.context_id = b.context_id and n.field = 'principal_amount'
where n.currency is distinct from h.principal_amount_currency
group by all order by 1, 2, n desc
limit 100
