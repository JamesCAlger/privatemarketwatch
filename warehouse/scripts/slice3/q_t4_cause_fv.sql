-- Slice 3 Task 4: per cause and detail (open rows of cmp_amount), rows, funds, report dates, and the fair value of the
-- affected positions (production's fair value of the row, published basis and JV basis apart), in $m.
with fv as (
    select accession, context_id, value_production as prod_fv from cmp_amount where field = 'fair_value'
)
select a.basis, a.cause, a.cause_detail, a.field, count(*) n
    , string_agg(distinct a.cik, ',' order by a.cik) as funds
    , min(a.report_date) as first_date, max(a.report_date) as last_date
    , round(sum(fv.prod_fv) / 1e6, 3) as fv_affected_m
from cmp_amount a
join fv on fv.accession = a.accession and fv.context_id = a.context_id
where a.cause is not null
group by all order by 1, 2, 3, 4
limit 100
