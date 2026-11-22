-- Baseline: cost pairs of cmp_amount where production's cost column differs from its cost_reported (the column the
-- comparison reads). They differ only where production fills cost from a donor row (pipeline/financial_conventions.py
-- cost_proxies, switched off by config.COST_PROXY_ENABLED). Measured 2026-11-22: 0. A rise means production started
-- filling cost by proxy and the comparison basis should be looked at again.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['cmp_amount_cost_columns_differ']) }}
select basis, cik, report_date, accession, context_id, value_production as cost_reported, value_production_cost as cost
from {{ ref('cmp_amount') }}
where field = 'cost' and value_production is distinct from value_production_cost
