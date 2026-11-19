-- One row per row-level fix, as loaded. Empty text becomes null, except value: an empty value on a
-- correction of kind value means the field is withdrawn, so value is kept as written.
select
    correction_id
    , cik
    , try_cast(nullif(report_date, '') as date) as report_date
    , accession
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
from {{ source('readings', 'correction') }}
