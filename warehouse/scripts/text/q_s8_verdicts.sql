-- Slice R phase 2 fix round 1: verdict counts per kind (positions; roles by role type). Read-only.
select proposal_kind, coalesce(role, '') as role_name, verdict, coalesce(reason, '') as why, count(*) n, sum(positions) positions
from int_text_proposal_verdict group by all order by 1, 2, 3, 4
