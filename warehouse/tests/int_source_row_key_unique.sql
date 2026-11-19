-- Exactly one role per context: accession and context_id are unique together, and every filed context of a parsed filing
-- of the five funds has a row.
select accession, context_id, count(*) as n
from {{ ref('int_source_row') }}
group by 1, 2
having count(*) > 1
union all
select cf.accession, cf.context_id, 0 as n
from {{ ref('int_context_feature') }} cf
semi join {{ ref('int_filing_candidate') }} c on c.accession = cf.accession
anti join {{ ref('int_source_row') }} r on r.accession = cf.accession and r.context_id = cf.context_id
