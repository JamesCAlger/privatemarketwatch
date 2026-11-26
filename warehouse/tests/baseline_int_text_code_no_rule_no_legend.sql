-- Text slice R phase 1 baseline (2026-11-26): codes printed in rate-candidate columns that no rule of the fund maps and
-- the filer's legend (as int_text_check_legend reads it) does not define (int_text_check_legend_code state neither),
-- against a ceiling set to the measured count (baseline_max.int_text_code_no_rule_no_legend). Measured 2026-11-26: 12
-- (fund, code) pairs: Ares 6 (plain rate names it prints with no quoted legend: SOFR, LIBOR, EURIBOR, CORRA, SONIA, "CAD Base
-- Rate"), BCRED 1 (the typo SORF), Blue Owl 1 (L), Apollo 4 (N, SONIA, and the words "Equity plus" and "Variable",
-- not rate codes). Listed in docs/baseline_text_rates_phase1_2026-11-26.md.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_code_no_rule_no_legend']) }}
select cik, code_key, printed_codes, rows
from {{ ref('int_text_check_legend_code') }}
where state = 'neither'
