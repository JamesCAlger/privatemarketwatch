-- One row per file of a scope fund in the two agent stores (var agent_store_dirs; slice 5 Task 2), on either side:
-- the file hashed when this view is read (build or test time) and the hash the readings loader recorded when it read the
-- store (readings manifest, key agent_store_sha256, keyed <store>/<fund folder>/<file>). changed: a file edited, added,
-- removed or renamed (retired) since the load, so the loaded corrections and rules are stale; run load_readings.ps1
-- again (tests/baseline_agent_store_changed_since_load.sql, ceiling 0). The same check stg_row_store_drift makes for
-- the row-correction CSVs.
-- Files are those production globs (<store>/*/*.json), in fund folders whose name does not start with '_' and whose
-- digits, padded to ten, are a scope fund; skipped files (retired, proposals) are hashed too, so retiring or reviving
-- one is seen. Hashes are text hashes (CRLF read as LF), the loader's store.text_sha256.
with scope as (
    select cik from {{ ref('stg_v05_scope') }}
)

, store_file as (
    {%- for name, dir in var('agent_store_dirs').items() %}
    select '{{ name }}' as store, filename, content from read_text('{{ dir }}/*/*.json')
    {{ "union all" if not loop.last }}
    {%- endfor %}
)

, current_file as (
    select
        store
        , regexp_extract(filename, '([^/\\]+)[/\\]([^/\\]+)$', 1) as fund_folder
        , regexp_extract(filename, '([^/\\]+)$', 1) as file_name
        , sha256(replace(content, chr(13) || chr(10), chr(10))) as sha256
    from store_file
)

, current_scoped as (
    select store || '/' || fund_folder || '/' || file_name as source_file, sha256
    from current_file
    where not starts_with(fund_folder, '_')
      -- lpad cuts a longer text to ten characters; the loader pads without cutting
      and length(regexp_replace(fund_folder, '[^0-9]', '', 'g')) <= 10
      and lpad(regexp_replace(fund_folder, '[^0-9]', '', 'g'), 10, '0') in (select cik from scope)
)

, recorded as (
    select k as source_file, json_extract_string(m.content, '$.agent_store_sha256."' || k || '"') as sha256
    from read_text('{{ var("readings_dir") }}/_manifest.json') m
    cross join unnest(coalesce(json_keys(m.content, '$.agent_store_sha256'), [])) as u(k)
)

select
    coalesce(c.source_file, r.source_file) as source_file
    , r.sha256 as loaded_sha256
    , c.sha256 as current_sha256
    , r.sha256 is distinct from c.sha256 as changed
from current_scoped c
full outer join recorded r on r.source_file = c.source_file
