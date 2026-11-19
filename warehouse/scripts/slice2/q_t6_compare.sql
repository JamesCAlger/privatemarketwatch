-- Task 6: every context whose role, rule, published flag, position rule or term-fact source changed against the
-- snapshot taken before the fund rules (out/t6_roles_before.parquet, from q_t5_snap_roles.sql), with production's
-- handling and the releasing rule. Run from the repository root through run_sql.py (paths relative to warehouse/).
with b as (select * from read_parquet('scripts/slice2/out/t6_roles_before.parquet'))
, p as (
    select accession_number as accession, src_context_id as context_id
        , bool_or(accounting_record_class is distinct from 'underlying_schedule') as published
        , bool_or(accounting_record_class = 'underlying_schedule') as jv
    from stg_holdings group by 1, 2
)
, a as (
    select r.*, cf.term_fact_source, cf.has_term_fact, cf.identifier_label, cf.fair_value
    from int_source_row r join int_context_feature cf using (accession, context_id)
)
select a.cik, b.role as role_before, a.role as role_after, b.is_published as pub_before, a.is_published as pub_after
    , coalesce(a.position_rule_id, case when a.term_fact_source <> 'standard' then a.term_fact_source end) as release_rule
    , case when p.published then 'publishes' when p.jv then 'jv' when x.cik is not null then 'lacks_filing' else 'leaves_out' end as production
    , count(*) as n
    , round(sum(a.fair_value) / 1e6, 1) as fv_m
from a join b using (accession, context_id)
left join p using (accession, context_id)
left join cmp_excluded_quarter x on x.cik = a.cik and x.report_date = a.report_date
where a.role is distinct from b.role or a.is_published is distinct from b.is_published
   or a.role_rule is distinct from b.role_rule or a.has_term_fact is distinct from b.has_term_fact
group by all
order by all
