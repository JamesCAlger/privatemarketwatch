-- Baseline (owner decision 2026-11-19): a production wrapper (var production_wrappers_dir) whose bytes, hashed when the
-- test runs (stg_wrapper_drift), differ from the hash recorded when the new pipeline's copy was taken
-- (warehouse/wrappers/_source.json). The new pipeline reads only its copy, so an edit made on the production side is
-- lost unless it is carried into the copy by hand; then update _source.json. Ceiling 0, severity error.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['production_wrapper_changed']) }}
select cik, copied_sha256, current_sha256
from {{ ref('stg_wrapper_drift') }}
where changed
