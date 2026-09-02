# dbt Round-Trip Spike (Phase 2 go/no-go)

Replays the duplicate-dimension-path defect class through a 2-model
dbt-duckdb port of the `bdc_dim_ranked` CTE cluster
(`pipeline/unified_holdings.py:1029-1066`) and tests whether a boundary
test failure converts into a B1-style packet.

Spec + kill criteria: docs/production_stack/production_data_stack_plan.md (Phase 2).
Decision report: docs/production_stack/dbt_spike_report.md.

Rerun order:
1. python spikes/dbt_roundtrip/extract_staged.py
2. cd spikes/dbt_roundtrip; $env:DBT_PROFILES_DIR = "."; dbt run; dbt test --store-failures
3. python spikes/dbt_roundtrip/failures_to_packet.py
4. python spikes/dbt_roundtrip/compare_and_verdict.py

All artifacts land in spikes/dbt_roundtrip/artifacts/ (git-ignored).
Never writes to data/output/ or frontend/public/data/.
