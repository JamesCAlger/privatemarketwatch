-- Baseline (owner decision 2026-11-19): a production wrapper (data/overrides/bdc_xbrl_wrappers) that changed since the
-- new pipeline's copy (warehouse/wrappers) was taken. The new pipeline reads only its copy, so an edit made on the
-- production side is lost unless it is carried into the copy by hand; then update warehouse/wrappers/_source.json.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['production_wrapper_changed']) }}
select cik, copied_sha256, current_sha256
from {{ ref('stg_wrapper_drift') }}
where changed
