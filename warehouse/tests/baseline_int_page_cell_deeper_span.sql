-- Text slice P2 baseline (2026-11-26): rows a rowspan reaches from two or more rows above, or from a row that is itself
-- covered (span_rule deeper_span): their columns are left naive rather than guessed. Ceiling
-- baseline_max.int_page_cell_deeper_span. Measured 2026-11-26: 0.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_page_cell_deeper_span']) }}
select distinct accession, table_index, row_index
from {{ ref('int_page_cell') }}
where span_rule = 'deeper_span'
