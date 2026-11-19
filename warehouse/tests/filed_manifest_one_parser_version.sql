-- All manifests carry one parser version, and it equals the parser_version of the filing rows. Returns the offenders.
select m.accession, m.parser_version as manifest_version, f.parser_version as filing_version
from (select distinct accession, parser_version from {{ ref('stg_filed_manifest') }}) m
full join {{ ref('stg_filed_filing') }} f on f.accession = m.accession
where m.parser_version is distinct from f.parser_version
union all
select null, string_agg(distinct parser_version, ',') as manifest_version, null
from {{ ref('stg_filed_manifest') }}
having count(distinct parser_version) > 1
union all
select null, null, string_agg(distinct parser_version, ',') as filing_version
from {{ ref('stg_filed_filing') }}
having count(distinct parser_version) > 1
