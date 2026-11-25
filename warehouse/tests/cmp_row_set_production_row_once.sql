-- Slice 5 Task 6 Part A (Task 5 review, minor): no production row is compared with two rows of this layer. Since Task 5
-- an adopted rate-only pair joins production's row at the giver to this layer's taker (cmp_row_set giver_to_taker), so
-- one production row could in principle meet two rows here (two takers of one giver). cmp_amount and cmp_rate would
-- then compare one production value twice. Ceiling 0: any row fails the build. Measured 2026-11-25: 0.
select basis, accession, production_context_id, count(*) as rows_here, string_agg(context_id, ';') as context_ids
from {{ ref('cmp_row_set') }}
where side = 'both'
group by 1, 2, 3
having count(*) > 1
