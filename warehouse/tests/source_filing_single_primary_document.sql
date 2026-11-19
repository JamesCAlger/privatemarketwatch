-- The staging model keeps one document per filing with min(); this checks the source really has one.
select accession_number, count(distinct primary_document) as documents
from {{ source('pipeline', 'bdc_filings_index') }}
where accession_number in (select accession_number from {{ ref('stg_holdings') }})
group by 1
having count(distinct primary_document) > 1