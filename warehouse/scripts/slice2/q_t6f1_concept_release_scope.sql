-- Task 6 fix round 1: rows in scope of tests/baseline_concept_rule_release_not_in_production.sql (position at rule 7
-- or 9, not cash, term fact only from a fund concept rule), by fund, rule action and concept, basis, whether the
-- quarter is compared, and whether production has the row on the same basis.
with p as (
    select accession_number as accession, src_context_id as context_id
        , accounting_record_class is distinct from 'underlying_schedule' as is_published
    from stg_holdings where src_context_id is not null
)
select s.cik, r.action, r.sel_concept_local, s.is_published
    , x.cik is null as compared_quarter
    , exists (select 1 from p where p.accession = s.accession and p.context_id = s.context_id
              and p.is_published = s.is_published) as production_has
    , count(*) as n
from int_source_row s
join int_context_feature cf using (accession, context_id)
join stg_reading_rule r on r.rule_id = cf.term_fact_source
left join cmp_excluded_quarter x on x.cik = s.cik and x.report_date = s.report_date
where s.role = 'position' and s.role_rule in (7, 9) and not s.is_cash
  and cf.term_fact_source is not null and cf.term_fact_source <> 'standard'
group by all
order by all
