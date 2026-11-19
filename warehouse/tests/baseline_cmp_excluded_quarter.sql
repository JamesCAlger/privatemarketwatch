-- Baseline (owner, 2026-11-19): fund-quarters left out of the comparison because production has no rows for them,
-- with the rows left out. Should fall to 0 when production is built with those filings.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['cmp_excluded_quarter']) }}
select cik, report_date, accessions, published_rows, unpublished_rows
from {{ ref('cmp_excluded_quarter') }}
