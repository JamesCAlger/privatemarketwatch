-- Baseline: every published holdings row's accession and src_context_id should exist as a context in the filed layer.
-- Published = not an underlying_schedule row. A blank or null src_context_id counts as not found.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['filed_context_missing']) }}
select h.cik, h.report_date, h.accession_number, h.src_context_id, count(*) as holdings_rows
from {{ ref('stg_holdings') }} h
left join {{ ref('stg_filed_context') }} c on c.accession = h.accession_number and c.context_id = h.src_context_id
where h.accounting_record_class is distinct from 'underlying_schedule' and c.context_id is null
group by 1, 2, 3, 4
