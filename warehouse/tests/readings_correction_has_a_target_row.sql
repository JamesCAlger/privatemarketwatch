-- Every correction names a context or a position label. One that names neither cannot be applied.
select correction_id, store, accession, field
from {{ ref('stg_correction') }}
where context_id is null and identifier is null
