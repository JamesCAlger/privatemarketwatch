-- Slice 5 Task 4: int_rate_normalised and int_rate_corrected_input give a taker of int_rate_adjacent its giver's rate
-- facts; int_field_reread (the contexts corrections make positions) does not. So no taker may be a context a
-- correction makes a position: such a taker would read no rate facts. Measured 2026-11-24: every taker is a filed
-- position.
select a.accession, a.taker_context_id, a.giver_context_id, r.row_reason
from {{ ref('int_rate_adjacent') }} a
join {{ ref('int_row_corrected') }} r on r.accession = a.accession and r.context_id = a.taker_context_id
where r.row_reason <> 'filed'
