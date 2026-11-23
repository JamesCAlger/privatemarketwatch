-- Rate rulings A and B: which int_field_normalised and cmp_rate rows changed between two snapshots (exported by
-- snapshot_tables.py), grouped. Paths are relative to warehouse/ (run_sql.py runs there); edit the two folder names
-- to the pair being compared. Run with scripts/slice2/run_sql.py.
with nb as (select * from read_parquet('../scratch/2026-11-23_rate_rulings/cmp/int_field_normalised_before.parquet'))
, na as (select * from read_parquet('../scratch/2026-11-23_rate_rulings/cmp/int_field_normalised_after.parquet'))
, cb as (select * from read_parquet('../scratch/2026-11-23_rate_rulings/cmp/cmp_rate_before.parquet'))
, ca as (select * from read_parquet('../scratch/2026-11-23_rate_rulings/cmp/cmp_rate_after.parquet'))
select 'int_field_normalised' as tbl, a.field, b.status || ' ' || b.reason as before, a.status || ' ' || a.reason as after
    , coalesce(a.action, '') as action_after, count(*) as n
from na a
join nb b on b.accession = a.accession and b.context_id = a.context_id and b.field = a.field
where a.value is distinct from b.value or a.status is distinct from b.status or a.reason is distinct from b.reason
   or a.rule_id is distinct from b.rule_id or a.action is distinct from b.action or a.value_filed is distinct from b.value_filed
   or a.rate_kind is distinct from b.rate_kind or a.value_date is distinct from b.value_date
group by all
union all
select 'cmp_rate ' || a.basis, a.field, b.outcome || ' ' || coalesce(b.cause || '|' || b.cause_detail, '-')
    , a.outcome || ' ' || coalesce(a.cause || '|' || a.cause_detail, '-'), '', count(*)
from ca a
join cb b on b.basis = a.basis and b.accession = a.accession and b.context_id = a.context_id and b.field = a.field
where a.outcome is distinct from b.outcome or a.cause_detail is distinct from b.cause_detail
   or a.value_new is distinct from b.value_new or a.text_new is distinct from b.text_new or a.date_new is distinct from b.date_new
   or a.new_reason is distinct from b.new_reason or a.new_rule_id is distinct from b.new_rule_id
group by all
order by 1, 2, 3, 4
