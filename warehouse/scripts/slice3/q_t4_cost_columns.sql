-- Slice 3 Task 4: how production's cost and cost_reported differ on the five funds, by donor-audit method.
select h.cik
    , coalesce(a.cost_method, '(no audit row)') as cost_method
    , count(*) as n_rows
    , count(*) filter (where h.cost is null) as cost_null
    , count(*) filter (where h.cost_reported is null) as cost_reported_null
    , count(*) filter (where h.cost is distinct from h.cost_reported) as cost_differs
from stg_holdings h
left join stg_cost_donor_audit a on a.row_id = h.row_id
group by all
order by 1, 2
limit 100
