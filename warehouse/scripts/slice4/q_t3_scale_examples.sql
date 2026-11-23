-- Slice 4 Task 3: up to four example rows per fund and field of a ratio-unit rate filed above 1, with the printed text
-- of the same fact beside the tag and, for comparison, the printed text of the other rate facts of the row.
with c as (
    select r.cik, r.field, r.report_date, r.accession, r.context_id, r.value_filed, r.unit, r.printed_text
        , row_number() over (partition by r.cik, r.field order by r.report_date desc, r.context_id) as k
    from int_field_read r
    where r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread') and r.status = 'read'
      and r.unit in ('pure', 'utr:Rate') and r.value_filed > 1
)
select c.cik, c.field, c.report_date, c.accession, c.context_id, c.value_filed, c.unit, c.printed_text
    , (select string_agg(o.field || '=' || coalesce(cast(o.value_filed as varchar), '') || ' [' || coalesce(o.printed_text, '') || ']', '; ')
       from int_field_read o where o.accession = c.accession and o.context_id = c.context_id
         and o.field in ('interest_rate_tag', 'pik_rate', 'spread') and o.field <> c.field and o.status = 'read') as other_rates
from c where k <= 4
order by 1, 2, 3
