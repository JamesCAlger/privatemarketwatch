-- Task 6 fix round 1: the HPS commitment lines released through its concept rule
-- (QualifiedAffordableHousingProjectInvestmentsCommitment as term fact): fair value sign counts and range, and the
-- positive ones listed with the commitment amount on the same context. Filed layer only.
with rel as (
    select s.accession, s.context_id, s.report_date, s.is_published, cf.identifier_label, cf.fair_value
    from int_source_row s
    join int_context_feature cf using (accession, context_id)
    join stg_reading_rule r on r.rule_id = cf.term_fact_source
    where s.role = 'position' and r.action = 'concept_is_term_fact'
      and r.sel_concept_local = 'QualifiedAffordableHousingProjectInvestmentsCommitment'
)
, commit_amt as (
    select f.accession, f.context_id, min(f.value_numeric) as commitment
    from stg_filed_fact f semi join rel using (accession, context_id)
    where f.concept_local = 'QualifiedAffordableHousingProjectInvestmentsCommitment'
    group by 1, 2
)
select 'summary' as part, null as report_date, null as label
    , count(*) filter (where fair_value > 0) || ' positive, ' || count(*) filter (where fair_value = 0) || ' zero, '
      || count(*) filter (where fair_value < 0) || ' negative; published ' || count(*) filter (where is_published)
      || '; min ' || min(fair_value) || ', max ' || max(fair_value) as detail
from rel
union all
select 'positive', cast(r.report_date as varchar), r.identifier_label
    , 'fair value ' || r.fair_value || '; commitment ' || c.commitment
from rel r left join commit_amt c using (accession, context_id)
where r.fair_value > 0
order by 1 desc, 3, 2
