-- Text slice R phase 1 baseline (2026-11-26): codes printed in rate-candidate columns that no rule of the fund maps and
-- the filer's legend (as int_text_check_legend reads it) does not define (int_text_check_legend_code state neither),
-- against a ceiling set to the measured count (baseline_max.int_text_code_no_rule_no_legend). Measured 2026-11-26: 12
-- (fund, code) pairs: one fund prints plain rate names with no quoted legend (SOFR, LIBOR, EURIBOR, CORRA, SONIA, "CAD
-- Base Rate"), one prints the typo SORF once, one prints L outside its legend, and one prints N and SONIA outside its
-- legend and the words "Equity plus" and "Variable", not rate codes. Listed by fund in docs/baseline_text_rates_phase1_2026-11-26.md.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_code_no_rule_no_legend']) }}
select cik, code_key, printed_codes, rows
from {{ ref('int_text_check_legend_code') }}
where state = 'neither'
