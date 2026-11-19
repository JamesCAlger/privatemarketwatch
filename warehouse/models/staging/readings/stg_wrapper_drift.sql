-- One row per fund in scope: the wrapper files hashed when this view is read (at build or test time), against the two
-- hashes on record. Owner decision 2026-11-19: the new pipeline reads its own wrapper copies.
--   (a) production side: the production wrapper (var production_wrappers_dir) now, against its SHA-256 when the copy
--       was taken (wrappers/_source.json) -> changed. An edit there must be carried into the copy by hand.
--   (b) copy side: the wrapper copy (var wrappers_dir) now, against the SHA-256 the readings loader recorded when it
--       read the copy (readings manifest, key wrapper_copy_sha256) -> copy_changed. The loaded rules are stale; run
--       load_readings.ps1 again.
-- Hashes are DuckDB sha256 over the file bytes (read_blob), the same SHA-256 the loader computes. A file that is
-- missing gives a null hash, which counts as changed. Paths come from vars so the CI fixture build passes its own.
with scope as (
    select cik from {{ ref('stg_v05_scope') }}
)

, production_file as (
    select regexp_extract(filename, '([^/\\]+)\.json$', 1) as cik, sha256(content) as sha256
    from read_blob('{{ var("production_wrappers_dir") }}/*.json')
)

, copy_file as (
    select regexp_extract(filename, '([^/\\]+)\.json$', 1) as cik, sha256(content) as sha256
    from read_blob('{{ var("wrappers_dir") }}/*.json')
)

, copy_record as (
    select content from read_text('{{ var("wrappers_dir") }}/_source.json')
)

, manifest as (
    select content from read_text('{{ var("readings_dir") }}/_manifest.json')
)

select
    s.cik
    , json_extract_string(r.content, '$.funds."' || s.cik || '".sha256') as copied_sha256
    , p.sha256 as current_sha256
    , json_extract_string(r.content, '$.funds."' || s.cik || '".sha256') is distinct from p.sha256 as changed
    , json_extract_string(m.content, '$.wrapper_copy_sha256."' || s.cik || '"') as loaded_copy_sha256
    , c.sha256 as copy_sha256
    , json_extract_string(m.content, '$.wrapper_copy_sha256."' || s.cik || '"') is distinct from c.sha256 as copy_changed
from scope s
cross join copy_record r
cross join manifest m
left join production_file p on p.cik = s.cik
left join copy_file c on c.cik = s.cik
