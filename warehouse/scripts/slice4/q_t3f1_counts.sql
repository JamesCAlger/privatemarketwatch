-- Slice 4 Task 3 fix round 1: (a) text_not_read and feature_missing rows on the rate fields per fund and quarter;
-- (b) rows of a fund with no rate reading whose plain rate tag carries a value and no PIK rate is read (production's
-- names_pik branch would give them kind all_in): their interest_rate status here.
select 'a' as part, n.cik, n.field, n.reason, string_agg(cast(n.report_date as varchar) || ':' || cast(c as varchar), ', ' order by n.report_date) as per_quarter, sum(c) as total
from (select cik, field, reason, report_date, count(*) as c from int_field_normalised
      where reason in ('text_not_read', 'feature_missing') group by all) n
group by all
union all
select 'b', r.cik, 'interest_rate', coalesce(n.status || ':' || n.reason, ''), '', count(*)
from int_field_read r
join int_field_normalised n on n.accession = r.accession and n.context_id = r.context_id and n.field = 'interest_rate'
where r.field = 'interest_rate_tag' and r.status = 'read' and not r.is_nil
  and r.cik not in (select cik from stg_reading_rule where action in ('rate_is_all_in', 'rate_is_cash_leg'))
  and not exists (select 1 from int_field_read p where p.accession = r.accession and p.context_id = r.context_id
                  and p.field = 'pik_rate' and p.status = 'read' and p.value_filed <> 0)
group by all
order by 1, 2, 3
