-- Baseline: fund and report dates production's holdings have and filing selection has no row for.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_filing_production_only']) }}
select distinct p.cik, p.report_date, p.accession_number as production_accession
from {{ ref('stg_holdings') }} p
anti join {{ ref('int_filing_selected') }} s on s.cik = p.cik and s.report_date = p.report_date
