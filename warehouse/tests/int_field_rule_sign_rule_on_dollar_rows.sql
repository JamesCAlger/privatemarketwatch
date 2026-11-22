-- bracketed_unsigned (priority 30) outranks reported_in_usd (20), but the two act on different things: the sign and
-- the unit. A row where the sign rule wins on an amount tagged in a foreign unit would leave the unit unread. Measured
-- 0 in slice 3 Task 3; a row here needs a decision on how the two combine.
select u.accession, u.context_id, u.field, r.unit
from {{ ref('int_field_rule') }} u
join {{ ref('int_field_read') }} r on r.accession = u.accession and r.context_id = u.context_id and r.field = u.field
where u.action = 'bracketed_unsigned' and r.unit <> 'iso4217:USD'
