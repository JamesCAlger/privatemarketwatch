-- Thin view over the filed-layer table fact_placement: columns by name, no logic.
select
    accession
    , fact_id
    , placement_index
    , ix_element
    , concept
    , context_id
    , row_index
    , cell_index
    , displayed_text
    , scale
    , sign
    , format
    , in_hidden
    , shown_row_index
    , shown_cell_index
from {{ source('filed', 'fact_placement') }}
