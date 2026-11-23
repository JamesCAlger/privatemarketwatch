-- Slice 4 Task 1 (owner decision 2026-11-23): commitment lines whose fair value is printed again on a line of the same
-- borrower in the same schedule (int_repeated_commitment_value). A flag, kept or dropped after reproduction; the rows
-- stay in every count until then. Measured 2026-11-23: 24, all on one fund's joint venture schedule (unpublished),
-- 2024-06-30 to 2026-06-30; they are the 24 of docs/baseline_amounts_2026-11-22.md (owner item 1). Nothing else is
-- flagged. Ceiling int_repeated_commitment_value; a rise fails the build.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_repeated_commitment_value']) }}
select accession, context_id, cik, report_date, scope, is_published, twin_context_id
from {{ ref('int_repeated_commitment_value') }}
where is_repeated_commitment_value
