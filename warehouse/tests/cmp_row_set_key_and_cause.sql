-- One row per (basis, accession, context_id); a row on both sides has no cause; a one-sided row has a cause from the
-- closed list (global constraints) and a detail.
select basis, accession, context_id, 'duplicate key' as problem
from {{ ref('cmp_row_set') }}
group by 1, 2, 3
having count(*) > 1
union all
select basis, accession, context_id, 'cause on a row on both sides'
from {{ ref('cmp_row_set') }}
where side = 'both' and (cause is not null or cause_detail is not null)
union all
select basis, accession, context_id, 'one-sided row without a cause from the list'
from {{ ref('cmp_row_set') }}
where side <> 'both'
  and (cause is null or cause_detail is null
       or cause not in ('old_wrong', 'new_wrong', 'convention', 'needs_store_not_loaded', 'needs_correction', 'not_yet_explained'))
