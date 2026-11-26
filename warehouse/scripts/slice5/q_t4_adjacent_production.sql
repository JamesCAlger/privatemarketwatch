-- Slice 5 Task 4 diagnostic: production's rows for the seven Ares taker / giver contexts (src_filled_fields, rates) and
-- the cmp_row_set rows labelled rate_only_context_pair. Read-only.
with pair(accession, taker, giver) as (values
    ('0001287750-24-000011', 'c-1206', 'c-1205'), ('0001287750-25-000020', 'c-1728', 'c-1727'),
    ('0001287750-25-000038', 'c-1268', 'c-1267'), ('0001287750-25-000038', 'c-1446', 'c-1445'),
    ('0001287750-25-000038', 'c-1776', 'c-1775'), ('0001287750-25-000046', 'c-1475', 'c-1474'),
    ('0001287750-25-000046', 'c-165', 'c-164'))
select 'holdings' as src, p.accession, p.taker, h.src_context_id, h.accounting_record_class, h.interest_rate, h.interest_rate_kind
    , h.interest_rate_cash, h.pik_rate, h.basis_spread, h.src_filled_fields, h.src_transforms
from pair p
left join stg_holdings h on h.accession_number = p.accession and h.src_context_id in (p.taker, p.giver)
union all
select 'cmp_row_set', c.accession, c.context_id, null, c.side, null, c.cause, null, null, null, c.cause_detail, null
from cmp_row_set c where c.cause_detail like '%rate_only%'
order by 1, 2, 3
