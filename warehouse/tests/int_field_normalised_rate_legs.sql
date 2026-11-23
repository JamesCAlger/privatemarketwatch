-- Spec section 7: cash leg plus PIK equals all-in, blocks the build. The rows are listed by int_rate_legs_check (a
-- model, so a dbt unit test can feed it a row that must fail).
select * from {{ ref('int_rate_legs_check') }}
