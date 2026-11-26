-- Slice 5 Task 4 diagnostic: the read state of the rate inputs on the targets of the rate corrections (BASE build), by
-- corrected field. Read-only.
with c as (
    select distinct a.accession, a.context_id, a.field_row, a.value_column
    from int_correction_application a where a.reason = 'rate_reading_not_rerun'
)
, r as (
    select accession, context_id
        , any_value(status || case when is_nil then '_nil' else '' end) filter (where field = 'interest_rate_tag') as it
        , any_value(status) filter (where field = 'interest_rate_cash_tag') as ct
        , any_value(status) filter (where field = 'pik_rate') as pk
        , any_value(status) filter (where field = 'spread') as sp
    from int_field_read where field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread')
    group by 1, 2
)
select c.field_row, c.value_column, r.it, r.ct, r.pk, r.sp, count(*) as n
from c left join r using (accession, context_id)
group by all order by 1, 2, n desc
