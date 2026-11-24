-- Slice 5 Task 2: no two corrections of one store set the same field of the same key (fund, report date, accession,
-- context id, identifier, row id, added position) with the same kind. Two such rows would be a repeat or a conflict
-- inside one store; Task 3 decides between stores (decision 7). Measured 2026-11-24: 0.
select store, kind, cik, report_date, accession, context_id, identifier, row_id, add_group_id, field, count(*) as n
from {{ ref('stg_correction') }}
group by all
having count(*) > 1
