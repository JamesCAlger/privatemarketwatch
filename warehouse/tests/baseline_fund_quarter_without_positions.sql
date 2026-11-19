-- Baseline: a fund-quarter that has financials should have positions.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['fund_quarter_without_positions']) }}
select cik, report_date, net_assets, investments_at_fair_value_filed
from {{ ref('fact_fund_period') }}
where not has_positions