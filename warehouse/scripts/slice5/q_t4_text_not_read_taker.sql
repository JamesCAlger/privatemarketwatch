-- Slice 5 Task 4 diagnostic: the adjacent-rate taker that takes a PIK rate only (Ares 0001287750-25-000038 c-1268),
-- against production's row. Read-only.
select src_context_id, issuer_name, interest_rate, interest_rate_kind, interest_rate_cash, pik_rate, basis_spread
    , src_transforms, interest_rate_source
from stg_holdings
where accession_number = '0001287750-25-000038' and src_context_id in ('c-1267', 'c-1268')
