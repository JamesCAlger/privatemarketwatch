-- Thin view over the filed-layer table tagged_fact: columns by name, no logic.
select
    accession
    , fact_id
    , fact_index
    , id_is_synthetic
    , concept
    , concept_namespace
    , concept_local
    , context_id
    , unit_id
    , value_text
    , value_numeric
    , decimals
    , precision
    , is_nil
    , value_length
    , value_sha256
    , value_truncated
from {{ source('filed', 'tagged_fact') }}
