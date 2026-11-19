-- Task 6 fix round 1: contexts whose role, published flag, position rule presence or term-fact presence changed against
-- the snapshot taken before the Blue Owl rule got its dates (out/t6f1_roles_before.parquet), plus the state of the
-- Insight CP blocker row. Expect: no changed row; the blocker row a position released by a position rule.
with b as (select * from read_parquet('scripts/slice2/out/t6f1_roles_before.parquet'))
select 'changed' as part, a.cik, a.accession, a.context_id, b.role as before, a.role as after
from int_source_row a join b using (accession, context_id)
where a.role is distinct from b.role or a.is_published is distinct from b.is_published
   or (a.position_rule_id is null) <> (b.position_rule_id is null)
union all
select 'blocker', s.cik, s.accession, s.context_id, cast(s.report_date as varchar), s.role || ' ' || coalesce(s.position_rule_id, '')
from int_source_row s join int_context_feature cf using (accession, context_id)
where cf.identifier_label = 'Insight CP (Blocker) Holdings, L.P. (dba CivicPlus, LLC)'
