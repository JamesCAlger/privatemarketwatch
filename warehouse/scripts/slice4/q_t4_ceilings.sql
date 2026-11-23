-- Slice 4 Task 4: cmp_rate rows per basis, field and cause, every cause of the closed list (0 where none), for the
-- ceilings var cmp_rate_max.
with causes as (
    select * from (values ('old_wrong'), ('new_wrong'), ('convention'), ('needs_correction'), ('needs_store_not_loaded'),
        ('production_stale'), ('owner_review'), ('not_yet_explained')) v(cause)
)
, fields as (
    select * from (values ('interest_rate'), ('interest_rate_cash'), ('pik_rate'), ('spread'), ('maturity_date'),
        ('rate_kind')) v(field)
)
, bases as (select * from (values ('published'), ('unpublished')) v(basis))
select b.basis, f.field, c.cause, count(r.accession) as n
from bases b cross join fields f cross join causes c
left join cmp_rate r on r.basis = b.basis and r.field = f.field and r.cause = c.cause
group by all
order by 1, 2, 3
