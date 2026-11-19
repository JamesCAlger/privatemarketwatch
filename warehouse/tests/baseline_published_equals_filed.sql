-- Baseline: published fair value should tie to the fund's filed investment total.
-- Compared without the cash rows where the evidence says the filed line leaves them out
-- (filed_total_excludes_cash in fact_fund_period).
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['published_equals_filed']) }}
select cik, report_date, investments_at_fair_value_filed, published_fair_value, cash_fair_value,
       filed_total_excludes_cash, difference_to_filed, difference_to_filed_on_basis
from {{ ref('fact_fund_period') }}
where has_positions and abs(difference_to_filed_on_basis) > {{ var('reconcile_tolerance') }}
