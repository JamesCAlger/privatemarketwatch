-- Slice 5 Task 3, a stop condition of the brief made a rule: a context corrections make a position must be one
-- production publishes (a holdings row with the same accession and context, not of class underlying_schedule), in the
-- quarters production has rows for (cmp_excluded_quarter lists the others; a promotion there is not checked here).
-- Agreement with production is not correctness: this checks only that the row rule adds no row production lacks.
select r.accession, r.context_id, r.cik, r.report_date, r.row_reason
from {{ ref('int_row_corrected') }} r
where r.row_reason <> 'filed'
  and exists (select 1 from {{ ref('stg_holdings') }} h where h.cik = r.cik and h.report_date = r.report_date)
  and not exists (
      select 1 from {{ ref('stg_holdings') }} h
      where h.accession_number = r.accession and h.src_context_id = r.context_id
        and coalesce(h.accounting_record_class, '') <> 'underlying_schedule'
  )
