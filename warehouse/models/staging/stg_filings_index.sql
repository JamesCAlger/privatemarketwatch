-- The index repeats accessions; the primary document does not differ within one.
select
    accession_number,
    min(primary_document) as primary_document
from {{ source('pipeline', 'bdc_filings_index') }}
where accession_number in (select accession_number from {{ ref('stg_holdings') }})
group by 1
