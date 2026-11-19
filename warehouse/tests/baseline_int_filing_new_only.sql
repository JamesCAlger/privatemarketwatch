-- Baseline: fund and report dates where filing selection chose a filing and production's holdings have no rows.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_filing_new_only']) }}
select s.cik, s.report_date, s.accession, s.selection_rule
from {{ ref('int_filing_selected') }} s
where s.accession is not null
  and not exists (
      select 1 from {{ ref('stg_holdings') }} p
      where p.cik = s.cik and p.report_date = s.report_date
  )
