-- One row per row-level fix, as loaded. Empty text becomes null, except value: an empty value on a
-- correction of kind value means the field is withdrawn, so value is kept as written.
-- Loader version 6 (slice 5 Task 2): kind add_row (one row per field of a position an agent rule adds, keyed by
-- accession and context id, grouped by add_group_id) and value corrections keyed by a production row_id (accession
-- null; Task 3 resolves the row). source_file names the store file the row came from.
select
    correction_id
    , cik
    , try_cast(nullif(report_date, '') as date) as report_date
    , nullif(accession, '') as accession
    , nullif(context_id, '') as context_id
    , nullif(identifier, '') as identifier
    , field
    , value
    , nullif(value_unit, '') as value_unit
    , nullif(expected_value, '') as expected_value
    , kind
    , store
    , nullif(reason, '') as reason
    , nullif(evidence, '') as evidence
    , nullif(author, '') as author
    , nullif(date_added, '') as date_added
    , report_date as report_date_text
    , nullif(row_id, '') as row_id
    , nullif(add_group_id, '') as add_group_id
    , source_file
from {{ source('readings', 'correction') }}
