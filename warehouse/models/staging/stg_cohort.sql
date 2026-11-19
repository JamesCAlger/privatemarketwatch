-- Cohort manifest: active entries, deferred entries and held-back funds.
with manifest as (
    select *
    from read_json('{{ var("cohort_manifest_file") }}')
)
select e.cik as cik, 'active' as cohort_status
from manifest, unnest(manifest.entries) as t(e)
union all
select e.cik, 'deferred'
from manifest, unnest(manifest.deferred_entries) as t(e)
union all
select c, 'held_back'
from manifest, unnest(manifest.held_back_ciks) as t(c)
