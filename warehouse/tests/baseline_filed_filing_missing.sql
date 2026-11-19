-- Baseline: every filing in dim_filing should have a row in the filed layer.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['filed_filing_missing']) }}
select d.accession_number, d.cik, d.report_date
from {{ ref('dim_filing') }} d
left join {{ ref('stg_filed_filing') }} f on f.accession = d.accession_number
where f.accession is null
