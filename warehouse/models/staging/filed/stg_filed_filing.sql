-- Thin view over the filed-layer table filing: columns by name, no logic.
select
    accession
    , cik
    , document_type
    , document_period_end_date
    , amendment_flag
    , fiscal_year_focus
    , fiscal_period_focus
    , registrant_name
    , dei_conflict
    , instance_file
    , instance_sha256
    , instance_bytes
    , html_file
    , html_sha256
    , html_bytes
    , parser_version
from {{ source('filed', 'filing') }}
