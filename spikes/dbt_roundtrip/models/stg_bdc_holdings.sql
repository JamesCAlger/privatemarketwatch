select
    *,
    'src:' || accession_number || ':' || coalesce(src_context_id, '') as source_row_id,
    regexp_replace(lower(trim(coalesce(cast(issuer_name as varchar), ''))),
                   '[^a-z0-9]+', ' ', 'g') as norm_issuer,
    regexp_replace(lower(trim(coalesce(cast(instrument_description as varchar), ''))),
                   '[^a-z0-9]+', ' ', 'g') as norm_instrument,
    round(coalesce(try_cast(fair_value as double), 0), 0) as fv_key,
    round(coalesce(try_cast(principal_amount as double), 0), 0) as principal_key,
    round(coalesce(try_cast(shares_held as double), 0), 0) as shares_key
from {{ source('spike', 'staged_predim') }}
