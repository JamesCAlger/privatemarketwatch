-- int_field_rule has one row per (accession, context_id, field), a row for every amount field int_field_read reads
-- (macro amount_rule_fields), and since slice 4 Task 3 a row for every rate rule field (macro rate_rule_fields) of
-- every position int_field_read reads.
select accession, context_id, field, count(*) as n, 'duplicate key' as problem
from {{ ref('int_field_rule') }}
group by 1, 2, 3
having count(*) > 1
union all
select r.accession, r.context_id, r.field, 0, 'read field with no rule row'
from {{ ref('int_field_read') }} r
anti join {{ ref('int_field_rule') }} u on u.accession = r.accession and u.context_id = r.context_id and u.field = r.field
where r.field in {{ amount_rule_fields() }}
union all
select r.accession, r.context_id, 'principal_amount_usd', 0, 'principal with no principal_amount_usd row'
from {{ ref('int_field_read') }} r
anti join {{ ref('int_field_rule') }} u
    on u.accession = r.accession and u.context_id = r.context_id and u.field = 'principal_amount_usd'
where r.field = 'principal_amount'
union all
select p.accession, p.context_id, f.field, 0, 'position with no rate rule row'
from (select distinct accession, context_id from {{ ref('int_field_read') }}) p
cross join (select unnest(list_value{{ rate_rule_fields() }}) as field) f
anti join {{ ref('int_field_rule') }} u on u.accession = p.accession and u.context_id = p.context_id and u.field = f.field
