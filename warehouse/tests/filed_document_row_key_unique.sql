-- Composite key of document_row must be unique. Returns the duplicated keys.
select accession, row_index, count(*) as n
from {{ ref('stg_filed_document_row') }}
group by 1,2
having count(*) > 1
