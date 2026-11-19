-- Thin view over the filed-layer table fact_footnote: columns by name, no logic.
select
    accession
    , fact_id
    , footnote_id
from {{ source('filed', 'fact_footnote') }}
