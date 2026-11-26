-- Text slice R fix round 1 (2026-11-26): the SOFR seed is a copy of data/reference/sofr_90day_avg.csv whose sha256 is
-- recorded (var sofr_seed_sha256; seeds/_seeds.yml). Hashed when the test runs, as stg_wrapper_drift hashes the
-- wrapper copies: DuckDB sha256 over the file's text with every CRLF read as LF, so a Windows checkout is not drift and
-- any edit is. The file is also '-text' in .gitattributes. Returns one row when the file is missing or its hash
-- differs. Reads the loaded seed too, so the test hangs off it.
with loaded as (
    select count(*) as n from {{ ref('sofr_90day_avg') }}
)

, file as (
    select sha256(replace(content, chr(13) || chr(10), chr(10))) as sha256
    from read_text('{{ var("sofr_seed_file") }}')
)

select '{{ var("sofr_seed_sha256") }}' as recorded_sha256, f.sha256 as file_sha256, l.n as loaded_rows
from loaded l
left join file f on true
where f.sha256 is distinct from '{{ var("sofr_seed_sha256") }}'
