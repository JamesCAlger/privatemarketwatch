-- Slice 4 Task 4 ruling change: rows of int_field_rule and int_field_normalised that changed against the snapshot of
-- the build at 990713e6 (any column of the before file), by table, field, before and after state. Every changed row
-- should be a rate field of a PIK-only row moving to text_not_read.
with nb as (select * from read_parquet('../scratch/2026-11-23_slice4_t4/rc/int_field_normalised_before.parquet'))
, rb as (select * from read_parquet('../scratch/2026-11-23_slice4_t4/rc/int_field_rule_before.parquet'))
, n_changed as (
    select a.field, coalesce(b.status, '-') || '|' || coalesce(b.reason, '-') as before_state,
        a.status || '|' || a.reason as after_state, a.value is null as value_now_null, b.value is not null as had_value
    from int_field_normalised a
    join nb b using (accession, context_id, field)
    where row(a.value, a.value_filed, a.action, a.rule_id, a.status, a.reason, a.rate_kind, a.value_date)
          is distinct from row(b.value, b.value_filed, b.action, b.rule_id, b.status, b.reason, b.rate_kind, b.value_date)
)
, r_changed as (
    select a.field, coalesce(b.resolution, '-') || '|' || coalesce(b.action, '-') as before_state,
        a.resolution || '|' || coalesce(a.action, '-') as after_state
    from int_field_rule a
    join rb b using (accession, context_id, field)
    where row(a.rule_id, a.action, a.resolution, a.priority, a.value_scale)
          is distinct from row(b.rule_id, b.action, b.resolution, b.priority, b.value_scale)
)
select 'int_field_normalised' as tbl, field, before_state, after_state, count(*) as n,
    count(*) filter (where had_value) as had_value, count(*) filter (where not value_now_null) as value_now
from n_changed group by all
union all
select 'int_field_rule', field, before_state, after_state, count(*), null, null from r_changed group by all
union all
select 'row_counts', 'normalised now/before', null, null, (select count(*) from int_field_normalised), (select count(*) from nb), null
union all
select 'row_counts', 'rule now/before', null, null, (select count(*) from int_field_rule), (select count(*) from rb), null
order by 1, 2, 3, 4
