-- Thin view over the filed-layer table unit: columns by name, no logic.
select
    accession
    , unit_id
    , numerator
    , denominator
from {{ source('filed', 'unit') }}
