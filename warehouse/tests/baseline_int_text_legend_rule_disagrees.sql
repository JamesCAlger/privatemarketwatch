-- Text slice R phase 1 baseline (2026-11-26): existing map_code rules the filer's own legend contradicts or defines two
-- ways in one filing (int_text_check_legend_rule state contradicts or mixed), against a ceiling set to the measured
-- count (baseline_max.int_text_legend_rule_disagrees). Measured 2026-11-26: 4, all mixed, none contradicts: three
-- transition legends (C defined as both CDOR and CORRA, B as both BBSW and BBSY, in one filing each) and one rule
-- S=SONIA whose fund's 2022-12-31 filing also defines S as SOFR. Listed in docs/baseline_text_rates_phase1_2026-11-26.md.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_legend_rule_disagrees']) }}
select rule_id, cik, parameter, state, legend_abbreviations
from {{ ref('int_text_check_legend_rule') }}
where state in ('contradicts', 'mixed')
