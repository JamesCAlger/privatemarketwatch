-- One filing per accession. A handful of rows carry a different form type from the rest of
-- their filing (see tests/baseline_filing_single_form_type.sql); the most common value is used.
select
    h.accession_number,
    min(h.cik)                    as cik,
    mode(h.form_type)             as form_type,
    max(h.filing_date)            as filing_date,
    mode(h.report_date)           as report_date,
    mode(h.form_type) like '%/A'  as is_amendment,
    min(f.primary_document)       as primary_document
from {{ ref('stg_holdings') }} h
left join {{ ref('stg_filings_index') }} f on f.accession_number = h.accession_number
group by 1
