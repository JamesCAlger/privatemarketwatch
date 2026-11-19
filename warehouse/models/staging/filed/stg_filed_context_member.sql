-- Thin view over the filed-layer table context_member: columns by name, no logic.
select
    accession
    , context_id
    , axis
    , member_index
    , member_kind
    , member
    , typed_element
    , container
from {{ source('filed', 'context_member') }}
