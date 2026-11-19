-- Thin view over the filed-layer table document_row: columns by name, no logic.
select
    accession
    , row_index
    , table_index
    , row_in_table
    , cell_count
    , cells
    , cell_colspans
    , cell_rowspans
    , fact_count
from {{ source('filed', 'document_row') }}
