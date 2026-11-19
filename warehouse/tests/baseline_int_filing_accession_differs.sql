-- Baseline: fund and report dates where the selected filing is not the one production's holdings use.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_filing_accession_differs']) }}
with production as (
    select distinct cik, report_date, accession_number
    from {{ ref('stg_holdings') }}
)
select s.cik, s.report_date, s.accession, p.accession_number as production_accession, s.refusal_reason
from {{ ref('int_filing_selected') }} s
join production p on p.cik = s.cik and p.report_date = s.report_date
where s.accession is distinct from p.accession_number
