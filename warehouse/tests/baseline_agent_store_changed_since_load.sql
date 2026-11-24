-- Baseline (slice 5 Task 2): a file of a scope fund in the two agent stores (var agent_store_dirs) whose text, hashed
-- when the test runs (stg_agent_store_drift), differs from the hash the readings loader recorded, or a file on one
-- side only (added, removed, retired by renaming). The loaded agent corrections and rules are then stale: run
-- load_readings.ps1 and build again. Ceiling 0, severity error, as for the row stores.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['agent_store_changed_since_load']) }}
select source_file, loaded_sha256, current_sha256
from {{ ref('stg_agent_store_drift') }}
where changed
