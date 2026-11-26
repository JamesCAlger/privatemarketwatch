-- The canonical value of each amount field and each rate field of each position row (spec intermediate_spine.md 6.4):
-- the union of int_amount_normalised (fair_value, cost, principal_amount, principal_amount_usd, shares,
-- pct_of_net_assets) and int_rate_normalised (interest_rate, interest_rate_cash, pik_rate, spread, maturity_date). One
-- row per (accession, context_id, field). Slice 5 Task 1 split the model in two, unchanged (the rate reading is macro
-- rate_reading); this view keeps the name, the columns and the rows every reader and test used before. Statuses,
-- reasons and what each action does are written in the two models' headers and the macro.
{{ config(materialized='view') }}
select * from {{ ref('int_amount_normalised') }}
union all
select * from {{ ref('int_rate_normalised') }}
