-- Thin view over the filed-layer table footnote: columns by name, no logic.
select
    accession
    , footnote_id
    , text
    , text_length
    , text_sha256
from {{ source('filed', 'footnote') }}
