-- Text slice R phase 1 baseline (2026-11-26): published positions whose rule-read reference-rate cell starts with a code
-- that no map_code or label_is_unspecified rule of the fund maps (int_text_reference_rate_read status code_not_mapped),
-- against a ceiling set to the measured count (baseline_max.int_text_reference_rate_code_not_mapped). Measured
-- 2026-11-26: 43,437. Nearly all are the common codes the wrappers never list because production maps them with a
-- global fallback this layer does not copy ('SOFR', 'S', 'SF', 'L', 'E', 'P', 'LIBOR', 'SONIA' ...); per fund and code in
-- docs/baseline_text_rates_phase1_2026-11-26.md. These are the agent's work (slice R, R3), not errors.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_reference_rate_code_not_mapped']) }}
select accession, context_id, cik, report_date, code
from {{ ref('int_text_reference_rate_read') }}
where is_published and status = 'code_not_mapped'
