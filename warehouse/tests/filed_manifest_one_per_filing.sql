-- Every filing folder has exactly one manifest and exactly one filing row, and the reverse. Returns the accessions that do not.
with m as (
    select accession, count(distinct manifest_file) as manifests
    from {{ ref('stg_filed_manifest') }}
    group by 1
), f as (
    select accession, count(*) as filing_rows
    from {{ ref('stg_filed_filing') }}
    group by 1
)
select coalesce(m.accession, f.accession) as accession, m.manifests, f.filing_rows
from m
full join f on f.accession = m.accession
where coalesce(m.manifests, 0) <> 1 or coalesce(f.filing_rows, 0) <> 1
