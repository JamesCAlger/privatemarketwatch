-- Baseline (slice 3 Task 1, item b): a row-correction store (var row_store_files) whose bytes, hashed when the test
-- runs (stg_row_store_drift), differ from the hash the readings loader recorded when it read the store (readings
-- manifest, inputs). The loaded corrections are then stale: run load_readings.ps1 and build again. A store with no
-- single entry on record counts as changed. Ceiling 0, severity error, as for the wrapper copies.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['row_store_changed_since_load']) }}
select store, path, manifest_entries, loaded_sha256, current_sha256
from {{ ref('stg_row_store_drift') }}
where changed
