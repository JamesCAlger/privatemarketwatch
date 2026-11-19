with nw as (
  select s.cik, s.report_date, sum(cf.fair_value) new_fv, count(*) n
  from int_source_row s join int_context_feature cf using (accession, context_id)
  where s.role='position' and s.is_published and not s.is_cash group by 1,2
)
select f.cik, f.report_date, f.investments_at_fair_value_filed filed, f.published_fair_value_ex_cash prod_ex_cash, nw.new_fv,
  f.published_fair_value_ex_cash - f.investments_at_fair_value_filed prod_diff, nw.new_fv - f.investments_at_fair_value_filed new_diff
from fact_fund_period f left join nw using (cik, report_date)
where f.cik in (select cik from stg_v05_scope)
order by 1,2
