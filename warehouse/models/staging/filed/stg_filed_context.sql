-- Thin view over the filed-layer table context: columns by name, no logic.
select
    accession
    , context_id
    , entity_scheme
    , entity_identifier
    , period_type
    , instant_date
    , start_date
    , end_date
    , member_count
from {{ source('filed', 'context') }}
