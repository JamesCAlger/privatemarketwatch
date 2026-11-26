-- Text slice R phase 1 baseline (2026-11-26): published positions whose table has no column an existing
-- read_printed_column rule names (int_text_reference_rate_read status column_not_found), against a ceiling set to the
-- measured count (baseline_max.int_text_reference_rate_column_not_found). Measured 2026-11-26: 2,272 = 2,271 positions
-- of one fund whose fair-value row is only in its unfunded-commitment table (a table with no rate column; the open
-- row-scope question of docs/baseline_page_structure_2026-11-26.md section 6) and 1 position in the one schedule table
-- without a header. Detail: docs/baseline_text_rates_phase1_2026-11-26.md.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_reference_rate_column_not_found']) }}
select accession, context_id, cik, report_date
from {{ ref('int_text_reference_rate_read') }}
where is_published and status = 'column_not_found'
