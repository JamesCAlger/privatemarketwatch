-- Text slice R phase 2 (2026-11-26): the two base-rate seeds downloaded from FRED (scripts/text/fetch_base_rates.py)
-- are unchanged since their sha256 was recorded (vars base_rate_fred_sha256, base_rate_series_sha256; seeds/_seeds.yml),
-- as tests/seed_sofr_hash_matches.sql checks the SOFR seed.
--   file    DuckDB sha256 over the file's text with every CRLF read as LF (a Windows checkout is not drift, any edit
--           is). Both files are '-text' in .gitattributes.
--   loaded  the loaded seed table against the file read now: md5 over the rows in key order, both sides typed the same
--           way. A file edited after the last dbt seed (a stale load) fails here.
-- Returns one row per failing side.
with file_hash as (
    select 'base_rate_fred' as seed, sha256(replace(content, chr(13) || chr(10), chr(10))) as sha256
        , '{{ var("base_rate_fred_sha256") }}' as expected
    from read_text('{{ var("base_rate_fred_file") }}')
    union all
    select 'base_rate_series', sha256(replace(content, chr(13) || chr(10), chr(10)))
        , '{{ var("base_rate_series_sha256") }}'
    from read_text('{{ var("base_rate_series_file") }}')
)

, fred_file as (
    select md5(string_agg(series_id || ',' || cast(date as varchar) || ',' || cast(value_pct as varchar), chr(10)
                          order by series_id, date)) as content_md5
    from read_csv('{{ var("base_rate_fred_file") }}', header = true,
                  columns = {'series_id': 'VARCHAR', 'date': 'DATE', 'value_pct': 'DOUBLE'})
)

, fred_loaded as (
    select md5(string_agg(series_id || ',' || cast(date as varchar) || ',' || cast(value_pct as varchar), chr(10)
                          order by series_id, date)) as content_md5
    from {{ ref('base_rate_fred') }}
)

, series_file as (
    select md5(string_agg(concat_ws('|', series_id, rate_name, frequency, kind, note), chr(10) order by series_id))
        as content_md5
    from read_csv('{{ var("base_rate_series_file") }}', header = true,
                  columns = {'series_id': 'VARCHAR', 'rate_name': 'VARCHAR', 'frequency': 'VARCHAR', 'kind': 'VARCHAR',
                             'note': 'VARCHAR'})
)

, series_loaded as (
    select md5(string_agg(concat_ws('|', series_id, rate_name, frequency, kind, note), chr(10) order by series_id))
        as content_md5
    from {{ ref('base_rate_series') }}
)

select seed || ' file' as side, expected, sha256 as found
from file_hash
where sha256 is distinct from expected
union all
select 'base_rate_fred loaded', f.content_md5, l.content_md5
from fred_file f cross join fred_loaded l
where f.content_md5 is distinct from l.content_md5
union all
select 'base_rate_series loaded', f.content_md5, l.content_md5
from series_file f cross join series_loaded l
where f.content_md5 is distinct from l.content_md5
