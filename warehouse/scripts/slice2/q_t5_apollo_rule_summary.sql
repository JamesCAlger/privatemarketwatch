-- Task 5, D12: summary of q_t5_apollo_rule_effect.sql, plus Apollo's published total (without cash) per quarter before
-- and after the rule against the filed total investments, and unresolved counts before and after.
with b as (select * from read_parquet('scripts/slice2/out/t5_roles_moved.parquet'))
, a as (select r.*, cf.fair_value from int_source_row r join int_context_feature cf using (accession, context_id))
, ch as (
    select b.cik, b.role || ' r' || b.role_rule || ' -> ' || a.role || ' r' || a.role_rule as change, a.reason like '%subtotal_on_fair_value%' as via_rule
        , b.accession, b.context_id
    from b join a using (accession, context_id)
    where b.role is distinct from a.role or b.role_rule is distinct from a.role_rule or b.is_published <> a.is_published
)
, prod as (select distinct accession_number as accession, src_context_id as context_id from stg_holdings
           where accounting_record_class is distinct from 'underlying_schedule')
, tot as (
    select x.report_date
        , sum(x.fair_value) filter (where x.side = 'b') as before_total
        , sum(x.fair_value) filter (where x.side = 'a') as after_total
    from (
        select 'b' as side, b.report_date, b.fair_value from b where b.cik = '0001837532' and b.role = 'position' and b.is_published and not b.is_cash
        union all
        select 'a', a.report_date, a.fair_value from a where a.cik = '0001837532' and a.role = 'position' and a.is_published and not a.is_cash
    ) x group by 1
)
select 'change' as k, cik, change, via_rule::varchar as detail, count(*) as n
    , count(*) filter (where exists (select 1 from prod p where p.accession = ch.accession and p.context_id = ch.context_id)) as production_published
    , null::double as before_total, null::double as after_total, null::double as filed
from ch group by all
union all
select 'unresolved', cik, 'before', null, count(*), null, null, null, null from b where role = 'unresolved' group by cik
union all
select 'unresolved', cik, 'after', null, count(*), null, null, null, null from a where role = 'unresolved' group by cik
union all
select 'apollo_total', '0001837532', t.report_date::varchar, null, null, null, t.before_total, t.after_total, f.investments_at_fair_value
from tot t left join stg_fund_financials f on f.cik = '0001837532' and f.report_date = t.report_date
order by 1, 2, 3
