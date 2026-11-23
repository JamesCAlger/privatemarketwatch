-- int_field_rule has one row per (accession, context_id, field), and a row for every amount field int_field_read reads
-- (the rate fields and the maturity date int_field_read also reads since slice 4 Task 2 get rules in Task 3).
select accession, context_id, field, count(*) as n, 'duplicate key' as problem
from {{ ref('int_field_rule') }}
group by 1, 2, 3
having count(*) > 1
union all
select r.accession, r.context_id, r.field, 0, 'read field with no rule row'
from {{ ref('int_field_read') }} r
anti join {{ ref('int_field_rule') }} u on u.accession = r.accession and u.context_id = r.context_id and u.field = r.field
where r.field in ('fair_value', 'cost', 'principal_amount', 'shares', 'pct_of_net_assets')
union all
select r.accession, r.context_id, 'principal_amount_usd', 0, 'principal with no principal_amount_usd row'
from {{ ref('int_field_read') }} r
anti join {{ ref('int_field_rule') }} u
    on u.accession = r.accession and u.context_id = r.context_id and u.field = 'principal_amount_usd'
where r.field = 'principal_amount'
