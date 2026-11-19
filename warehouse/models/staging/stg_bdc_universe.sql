select
    lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') as cik,
    nullif(vehicle_type, '')                              as vehicle_type,
    nullif(status, '')                                    as status,
    try_cast(election_date as date)                       as bdc_election_date,
    try_cast(first_filing_date as date)                   as first_filing_date
from {{ source('pipeline', 'bdc_universe') }}
where lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') in (select cik from {{ ref('stg_v05_scope') }})
