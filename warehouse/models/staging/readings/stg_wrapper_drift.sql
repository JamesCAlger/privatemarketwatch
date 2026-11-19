-- One row per fund: the production wrapper's SHA-256 when the new pipeline's copy was taken (warehouse/wrappers/
-- _source.json) and now, and whether it changed. No logic; the loader computed it.
select
    cik
    , copied_sha256
    , nullif(current_sha256, '') as current_sha256
    , changed
from {{ source('readings', 'wrapper_drift') }}
