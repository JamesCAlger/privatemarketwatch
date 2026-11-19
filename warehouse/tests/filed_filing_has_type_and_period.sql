-- Every filing row has a document type and a document period end date. Returns the filings that lack either.
select accession, cik, document_type, document_period_end_date
from {{ ref('stg_filed_filing') }}
where document_type is null or document_period_end_date is null
