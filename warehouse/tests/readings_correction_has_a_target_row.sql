-- Every correction names a context, a position label or (an agent B2 leaf, slice 5 Task 2) a production row id. One
-- that names none cannot be applied.
select correction_id, store, accession, field
from {{ ref('stg_correction') }}
where context_id is null and identifier is null and row_id is null
