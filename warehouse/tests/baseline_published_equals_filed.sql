-- Baseline: published fair value should tie to the fund's filed investment total.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['published_equals_filed']) }}
select cik, report_date, investments_at_fair_value_filed, published_fair_value, difference_to_filed
from {{ ref('fact_fund_period') }}
where has_positions and abs(difference_to_filed) > {{ var('reconcile_tolerance') }}
