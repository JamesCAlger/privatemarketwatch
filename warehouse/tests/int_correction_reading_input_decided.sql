-- Slice 5 Task 4: every correction of a rate reading input that passes the screen and acts on a position is decided
-- on a run of the rate reading: its field row has a row of int_rate_corrected run corrected. Without it the outcome
-- would rest on an empty change flag.
select a.correction_id, a.accession, a.context_id, a.field_row, a.outcome, a.reason
from {{ ref('int_correction_application') }} a
where a.step = 'reading_input' and a.outcome in ('applied', 'no_op', 'failed')
  and not exists (
      select 1 from {{ ref('int_rate_corrected') }} c
      where c.run = 'corrected' and c.accession = a.accession and c.context_id = a.context_id and c.field = a.field_row
  )
