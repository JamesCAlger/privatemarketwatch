-- One filing row per folder under the filed directory, and the row agrees with its folder (accession, cik).
with files as (
    select
        filename,
        regexp_extract(filename, 'cik=([0-9]+)', 1)               as folder_cik,
        regexp_extract(filename, 'accession=([0-9-]+)', 1)        as folder_accession,
        accession, cik
    from read_parquet('{{ var("filed_dir") }}/*/*/filing.parquet', hive_partitioning=false, filename=true, union_by_name=true)
)
select filename, folder_cik, folder_accession, accession, cik
from files
where accession <> folder_accession or cik <> folder_cik
union all
select filename, null, null, null, null
from (select filename, count(*) n from files group by 1 having count(*) <> 1)
