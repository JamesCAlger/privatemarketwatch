-- Slice 5 Task 3: no correction is dropped. Every loaded correction has at least one row in int_correction_application,
-- and the application has exactly the rows of int_correction_target (same grain, nothing added or lost on the way).
select 'no outcome' as problem, c.correction_id
from {{ ref('stg_correction') }} c
anti join {{ ref('int_correction_application') }} a on a.correction_id = c.correction_id
union all
select 'target rows differ', correction_id
from (
    select correction_id, accession, context_id from {{ ref('int_correction_target') }}
    except all
    select correction_id, accession, context_id from {{ ref('int_correction_application') }}
)
union all
select 'application rows differ', correction_id
from (
    select correction_id, accession, context_id from {{ ref('int_correction_application') }}
    except all
    select correction_id, accession, context_id from {{ ref('int_correction_target') }}
)
