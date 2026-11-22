-- int_field_normalised has one row per (accession, context_id, field) and the same rows as int_field_rule.
select accession, context_id, field, count(*) as n, 'duplicate key' as problem
from {{ ref('int_field_normalised') }}
group by 1, 2, 3
having count(*) > 1
union all
select u.accession, u.context_id, u.field, 0, 'rule row with no normalised row'
from {{ ref('int_field_rule') }} u
anti join {{ ref('int_field_normalised') }} n
    on n.accession = u.accession and n.context_id = u.context_id and n.field = u.field
