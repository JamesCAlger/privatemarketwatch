-- Baseline (spec section 8): production rows of the five funds with no context id. They cannot be joined to this layer
-- and are listed here instead of in cmp_row_set.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['cmp_row_set_no_context']) }}
select cik, report_date, accession_number, row_id, accounting_record_class, fair_value
from {{ ref('stg_holdings') }}
where src_context_id is null
