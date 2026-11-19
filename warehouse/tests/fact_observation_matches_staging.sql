-- The fact must hold exactly the staged rows: same count, same total fair value.
-- A join that duplicated or dropped rows would show here.
with staged as (
    select count(*) as n, sum(fair_value) as fv from {{ ref('stg_holdings') }}
),
fact as (
    select count(*) as n, sum(fair_value) as fv from {{ ref('fact_observation') }}
)
select staged.n as staged_rows, fact.n as fact_rows, staged.fv as staged_fv, fact.fv as fact_fv
from staged, fact
where staged.n <> fact.n
   or abs(staged.fv - fact.fv) > 0.005
