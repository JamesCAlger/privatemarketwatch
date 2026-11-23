-- Decides which positions fail the legs check of spec section 7: where the all-in rate, the cash leg and the PIK rate
-- are all normalised, the cash leg plus the PIK rate must equal the all-in rate within var rate_legs_tolerance (float
-- rounding only; slice 4 Task 3). One row per failing position; empty when the check holds.
-- tests/int_field_normalised_rate_legs.sql fails the build on any row. A model, not only a test, so that a dbt unit
-- test can feed it a hand-made row that must fail. The check cannot fail on today's code (the cash leg is computed as
-- all-in less PIK, so the sum holds by construction): it is a regression guard on the arithmetic, not evidence about
-- the data.
{{ config(materialized='view') }}
with leg as (
    select
        accession
        , context_id
        , any_value(cik) as cik
        , any_value(report_date) as report_date
        , any_value(value) filter (where field = 'interest_rate' and status = 'normalised') as all_in
        , any_value(value) filter (where field = 'interest_rate_cash' and status = 'normalised') as cash
        , any_value(value) filter (where field = 'pik_rate' and status = 'normalised') as pik
    from {{ ref('int_field_normalised') }}
    where field in ('interest_rate', 'interest_rate_cash', 'pik_rate')
    group by 1, 2
)

select accession, context_id, cik, report_date, all_in, cash, pik, cash + pik - all_in as difference
from leg
where all_in is not null and cash is not null and pik is not null
  and abs(cash + pik - all_in) > {{ var('rate_legs_tolerance') }}
