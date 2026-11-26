-- Text slice P3 baseline (2026-11-26; fix round 1 widened it to every row role), a fund-neutral rule: within one
-- schedule table, the placed facts read as one field (macro page_field_fact: positions' facts as int_field_read reads
-- them, and on any other row (subtotals, totals) the standard concepts of seed concept_map; a hidden fact counts in the
-- cell that shows it) should fall under one header signature. One row per (accession, table_index, field) where they
-- fall under two or more, against a ceiling set to the measured count (baseline_max.int_page_field_split_columns).
-- Facts in cells given no column (column_rule none_*) are counted by baseline_int_page_field_fact_no_column instead.
-- Measured 2026-11-26 (fix round 1): see the ceiling and docs/baseline_page_structure_2026-11-26.md section 4. In every
-- case looked at, the filer prints the odd value in the neighbouring rate column (a PIK coupon such as "13.75% PIK" in
-- "Reference Rate and Spread", or a coupon "12.55% (4.13% PIK)" carrying the spread tag in "Coupon"); the split is the
-- filer's. Detail query: scripts/text/q_p1_split_detail.sql.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_page_field_split_columns']) }}
with f as ({{ page_field_fact() }})
select accession, table_index, field, count(distinct header_signature) as signatures
from f
where header_signature is not null
group by 1, 2, 3
having count(distinct header_signature) > 1
