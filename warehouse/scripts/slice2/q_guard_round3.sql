-- Fix round 3 guard: compare roles with the filer_concept seed (int_source_row now) against roles with an empty seed
-- (scripts/slice2/out/roles_without_seed.parquet, identical to round 2).
with b as (select * from read_parquet('scripts/slice2/out/roles_without_seed.parquet'))
, a as (select r.*, cf.fair_value_source, cf.term_fact_source from int_source_row r join int_context_feature cf using (accession, context_id))
, j as (
  select b.cik, b.role as role_before, b.role_rule as rule_before, a.role as role_after, a.role_rule as rule_after
    , a.filer_concept_id, a.fair_value_source, a.term_fact_source, a.report_date
  from b join a using (accession, context_id)
)
select 'changed' k, cik, role_before || ' r' || rule_before || ' -> ' || role_after || ' r' || rule_after as change
  , case when filer_concept_id is not null then 'via filer concept'
         when fair_value_source not in ('standard') or term_fact_source not in ('standard') then 'filer fact present, no id'
         else 'no filer fact on row' end as how
  , count(*) n
from j where role_before <> role_after or rule_before <> rule_after
group by all
union all
select 'aggregate_before_changed', cik, role_before || ' -> ' || role_after, '', count(*)
from j where role_before = 'aggregate' and (role_after <> 'aggregate' or rule_after <> rule_before) group by all
union all
select 'row_count', '', (select count(*) from b)::varchar, (select count(*) from a)::varchar, 0
order by 1, 2, 3
