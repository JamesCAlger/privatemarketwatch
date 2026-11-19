-- Baseline: fund and report dates where filing selection refused to choose a filing.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_filing_refused']) }}
select cik, report_date, refusal_reason, candidate_count, measure
from {{ ref('int_filing_selected') }}
where refusal_reason is not null
