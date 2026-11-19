-- Baseline (final fix wave F1): a wrapper copy (var wrappers_dir) whose bytes, hashed when the test runs
-- (stg_wrapper_drift), differ from the hash the readings loader recorded when it read the copy (readings manifest,
-- wrapper_copy_sha256). The loaded rules are then stale: run load_readings.ps1 and build again. A copy with no hash on
-- record (readings from an older loader) counts as changed. Ceiling 0, severity error.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['wrapper_copy_changed_since_load']) }}
select cik, loaded_copy_sha256, copy_sha256
from {{ ref('stg_wrapper_drift') }}
where copy_changed
