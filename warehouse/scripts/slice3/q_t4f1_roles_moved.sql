-- Slice 3 Task 4 fix round 1, guard: contexts whose role decision, feature fair value or cost, or row-set comparison
-- differs between the snapshot taken before the fixes and now (expected: none), and the counts on each side.
with b as (select * from read_parquet('scripts/slice3/out/t4f1_roles_before.parquet'))
, a as (
    select s.accession, s.context_id, s.role, s.role_rule, s.reason, s.is_published, s.is_cash, s.rule_id
        , cf.fair_value, cf.cost, cf.has_term_fact, c.basis, c.side, c.cause, c.cause_detail
    from int_source_row s
    left join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    left join cmp_row_set c on c.accession = s.accession and c.context_id = s.context_id
)
select 'rows before' as what, count(*) as n from b
union all select 'rows after', count(*) from a
union all select 'cmp_row_set rows before', count(side) from b
union all select 'cmp_row_set rows after', count(side) from a
union all
select 'moved', count(*) from (
    select * from b except select * from a
    union all
    select * from a except select * from b
) d
