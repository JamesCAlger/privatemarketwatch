select
    cik,
    report_date,
    position_id,
    accession_number,
    fair_value,
    nullif(pik_current_status, '') as pik_current_status,
    pik_terms_flag
from {{ source('pipeline', 'position_pik_status') }}
where cik in (select cik from {{ ref('stg_v05_scope') }})