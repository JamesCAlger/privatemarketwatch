-- For every filing and each of the nine tables, the manifest row count equals the number of rows with that accession
-- in the table. Catches a missing or empty table file (it contributes no rows) and rows with no manifest.
with actual as (
    select accession, 'filing' as table_name, count(*) as n from {{ ref('stg_filed_filing') }} group by 1
    union all select accession, 'context', count(*) from {{ ref('stg_filed_context') }} group by 1
    union all select accession, 'context_member', count(*) from {{ ref('stg_filed_context_member') }} group by 1
    union all select accession, 'unit', count(*) from {{ ref('stg_filed_unit') }} group by 1
    union all select accession, 'tagged_fact', count(*) from {{ ref('stg_filed_fact') }} group by 1
    union all select accession, 'document_row', count(*) from {{ ref('stg_filed_document_row') }} group by 1
    union all select accession, 'fact_placement', count(*) from {{ ref('stg_filed_fact_placement') }} group by 1
    union all select accession, 'footnote', count(*) from {{ ref('stg_filed_footnote') }} group by 1
    union all select accession, 'fact_footnote', count(*) from {{ ref('stg_filed_fact_footnote') }} group by 1
)
select
    coalesce(m.accession, a.accession) as accession
    , coalesce(m.table_name, a.table_name) as table_name
    , m.manifest_rows
    , coalesce(a.n, 0) as table_rows
from {{ ref('stg_filed_manifest') }} m
full join actual a on a.accession = m.accession and a.table_name = m.table_name
where m.manifest_rows is null or m.manifest_rows <> coalesce(a.n, 0)
