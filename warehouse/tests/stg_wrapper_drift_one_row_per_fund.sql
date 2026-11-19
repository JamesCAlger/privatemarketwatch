-- Exactly one drift row per fund in scope (stg_v05_scope), so an empty or partial drift table cannot pass
-- tests/baseline_production_wrapper_changed.sql. Lists funds with no row, with more than one, or not in scope.
with d as (select cik, count(*) as n from {{ ref('stg_wrapper_drift') }} group by 1)
select coalesce(s.cik, d.cik) as cik, coalesce(d.n, 0) as drift_rows, s.cik is not null as in_scope
from {{ ref('stg_v05_scope') }} s
full join d on d.cik = s.cik
where s.cik is null or d.cik is null or d.n <> 1
