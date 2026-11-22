-- Slice 3 Task 4: in one filing (variable acc), the principal pairs by this layer's principal action and the outcome,
-- with how many production rows hold a principal and no shares (production's par-from-count rows look like this).
select a.basis, a.new_action, a.outcome, count(*) n
    , count(*) filter (where h.principal_amount is not null and h.shares_held is null) as prod_principal_no_shares
    , count(*) filter (where h.principal_amount_currency is null and h.principal_amount is not null) as prod_principal_blank_currency
from cmp_amount a
join stg_holdings h on h.accession_number = a.accession and h.src_context_id = a.context_id
where a.accession = getvariable('acc') and a.field = 'principal_amount'
group by all order by 1, 2, 3
limit 50
