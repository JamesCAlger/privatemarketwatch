-- One row per row-correction store the readings loader reads: the store file hashed when this view is read (at build
-- or test time), against the SHA-256 the loader recorded when it read the store (readings manifest, key inputs). A
-- store edited after the last load means the loaded corrections are stale: run load_readings.ps1 again (slice 3
-- Task 1, item b; the same check stg_wrapper_drift makes for the wrapper copies).
-- The manifest records each input under the path the loader was given, which is relative to the repository root
-- (or absolute in the CI fixture build), while dbt's paths are relative to warehouse/. So a store is matched to its
-- manifest entry by file name. No entry, or more than one, counts as changed. A missing store file fails the build
-- when the view is read. Paths come from var row_store_files, so the CI fixture build passes its own.
with store as (
    select * from (values
    {%- for name, path in var('row_store_files').items() %}
        ('{{ name }}', '{{ path }}'){{ "," if not loop.last }}
    {%- endfor %}
    ) as t(store, path)
)

, store_file as (
    select regexp_extract(filename, '([^/\\]+)$', 1) as file_name, sha256(content) as sha256
    from read_blob([
    {%- for name, path in var('row_store_files').items() %}
        '{{ path }}'{{ "," if not loop.last }}
    {%- endfor %}
    ])
)

, manifest_input as (
    select
        regexp_extract(k, '([^/\\]+)$', 1) as file_name
        , json_extract_string(m.content, '$.inputs."' || k || '"') as sha256
    from read_text('{{ var("readings_dir") }}/_manifest.json') m
    cross join unnest(json_keys(m.content, '$.inputs')) as u(k)
)

, recorded as (
    select file_name, count(*) as entries, min(sha256) as sha256
    from manifest_input
    group by 1
)

select
    s.store
    , s.path
    , r.entries as manifest_entries
    , r.sha256 as loaded_sha256
    , f.sha256 as current_sha256
    , coalesce(r.entries, 0) <> 1 or r.sha256 is distinct from f.sha256 as changed
from store s
left join store_file f on f.file_name = regexp_extract(s.path, '([^/\\]+)$', 1)
left join recorded r on r.file_name = regexp_extract(s.path, '([^/\\]+)$', 1)
