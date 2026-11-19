-- Wrapper declarations the loader does not turn into a rule, with the reason. No logic.
select
    cik
    , wrapper_key
    , entry
    , reason
from {{ source('readings', 'not_loaded') }}
