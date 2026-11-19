-- One row per (basis, accession, context_id), and no (accession, context_id) in both bases, so (accession,
-- context_id) is unique too; a row on both sides has no cause; a one-sided row has a cause from the closed list
-- (global constraints, amended by the controller 2026-11-19) and a detail.
select basis, accession, context_id, 'duplicate key' as problem
from {{ ref('cmp_row_set') }}
group by 1, 2, 3
having count(*) > 1
union all
select min(basis), accession, context_id, 'context in both bases'
from {{ ref('cmp_row_set') }}
group by 2, 3
having count(distinct basis) > 1
union all
select basis, accession, context_id, 'cause on a row on both sides'
from {{ ref('cmp_row_set') }}
where side = 'both' and (cause is not null or cause_detail is not null)
union all
select basis, accession, context_id, 'one-sided row without a cause from the list'
from {{ ref('cmp_row_set') }}
where side <> 'both'
  and (cause is null or cause_detail is null
       or cause not in ('old_wrong', 'new_wrong', 'convention', 'needs_store_not_loaded',
                        'needs_correction', 'owner_review', 'not_yet_explained'))
