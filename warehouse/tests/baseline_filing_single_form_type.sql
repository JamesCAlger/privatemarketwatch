-- Baseline: every holdings row of a filing should carry the same form type and report date.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['filing_single_form_type']) }}
select
    accession_number,
    count(distinct form_type)   as form_types,
    count(distinct report_date) as report_dates
from {{ ref('stg_holdings') }}
group by 1
having count(distinct form_type) > 1 or count(distinct report_date) > 1
