-- Text slice R fix round 1 (2026-11-26; loaded content added in fix round 2): the SOFR seed is a copy of
-- data/reference/sofr_90day_avg.csv whose sha256 is recorded (var sofr_seed_sha256; seeds/_seeds.yml).
--   file    the file hashed when the test runs, as stg_wrapper_drift hashes the wrapper copies: DuckDB sha256 over the
--           file's text with every CRLF read as LF, so a Windows checkout is not drift and any edit is. The file is also
--           '-text' in .gitattributes.
--   loaded  the loaded seed table against the file read now: md5 over 'date,value' lines in date order, both sides
--           typed the same way (date, double). A file edited after the last dbt seed (a stale load) fails here.
-- Returns one row per failing side.
with file_hash as (
    select sha256(replace(content, chr(13) || chr(10), chr(10))) as sha256
    from read_text('{{ var("sofr_seed_file") }}')
)

, file_rows as (
    select md5(string_agg(cast(date as varchar) || ',' || cast(sofr_90day_avg_pct as varchar), chr(10) order by date))
        as content_md5
    from read_csv('{{ var("sofr_seed_file") }}', header = true,
                  columns = {'date': 'DATE', 'sofr_90day_avg_pct': 'DOUBLE'})
)

, loaded_rows as (
    select md5(string_agg(cast(date as varchar) || ',' || cast(sofr_90day_avg_pct as varchar), chr(10) order by date))
        as content_md5
    from {{ ref('sofr_90day_avg') }}
)

select 'file' as side, '{{ var("sofr_seed_sha256") }}' as expected, f.sha256 as found
from (select 1) x
left join file_hash f on true
where f.sha256 is distinct from '{{ var("sofr_seed_sha256") }}'
union all
select 'loaded', fr.content_md5, lr.content_md5
from file_rows fr
cross join loaded_rows lr
where fr.content_md5 is distinct from lr.content_md5
