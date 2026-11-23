-- Slice 4 Task 3: rate read fields filed above 1 in a ratio unit (pure, utr:Rate), the scale_not_decided candidates:
-- per fund, field and quarter. Second part (run q_t3_scale_examples.sql): example rows with the printed text.
select r.cik, r.field, r.report_date, r.unit, count(*) as n, min(r.value_filed) as min_filed, max(r.value_filed) as max_filed
from int_field_read r
where r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread') and r.status = 'read'
  and r.unit in ('pure', 'utr:Rate') and r.value_filed > 1
group by all
order by 1, 2, 3
