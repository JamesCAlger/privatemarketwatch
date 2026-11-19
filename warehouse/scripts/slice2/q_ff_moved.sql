-- Final fix wave: every context whose role, rule, cash flag or published flag changed against the snapshot taken before
-- the wave (out/ff_roles_before.parquet), and every cmp_row_set row whose side or cause changed (out/ff_cmp_before.parquet).
-- The cash detail was renamed in F2 (cash_published_d7 -> cash_published_d7_<source>), so the cause key is compared
-- with that rename undone. Paths relative to warehouse/ (run through run_sql.py).
with rb as (select * from read_parquet('scripts/slice2/out/ff_roles_before.parquet'))
, roles as (
    select 'role' as what, a.cik, a.report_date, a.accession, a.context_id, b.identifier_label
        , b.role || '/' || b.role_rule || '/cash=' || b.is_cash || '/pub=' || b.is_published as before
        , a.role || '/' || a.role_rule || '/cash=' || a.is_cash || '/pub=' || a.is_published as after
    from int_source_row a
    join rb b using (accession, context_id)
    where a.role is distinct from b.role or a.role_rule is distinct from b.role_rule
       or a.is_cash is distinct from b.is_cash or a.is_published is distinct from b.is_published
)
, cb as (select * from read_parquet('scripts/slice2/out/ff_cmp_before.parquet'))
, ca as (
    select c.*, cf.identifier_label from cmp_row_set c left join int_context_feature cf using (accession, context_id)
)
, cmp as (
    select 'cmp' as what, coalesce(a.cik, b.cik) as cik, coalesce(a.report_date, b.report_date) as report_date
        , coalesce(a.accession, b.accession) as accession, coalesce(a.context_id, b.context_id) as context_id
        , coalesce(a.identifier_label, b.identifier_label) as identifier_label
        , b.basis || '/' || b.side || '/' || coalesce(b.cause, '') || '|' || coalesce(b.cause_detail, '') as before
        , a.basis || '/' || a.side || '/' || coalesce(a.cause, '') || '|' || coalesce(a.cause_detail, '') as after
    from ca a
    full join cb b on a.basis = b.basis and a.accession = b.accession and a.context_id = b.context_id
    where a.accession is null or b.accession is null or a.side is distinct from b.side
       or a.cause is distinct from b.cause
       or regexp_replace(coalesce(a.cause_detail, ''), '^cash_published_d7_.*$', 'cash_published_d7')
          is distinct from coalesce(b.cause_detail, '')
)
select * from roles
union all
select * from cmp
order by what, cik, report_date, context_id
