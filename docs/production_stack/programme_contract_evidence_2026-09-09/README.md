# Saved contract-resolution evidence

Produced by the bounded cache-only collector on 2026-09-09. See the
[assessment report](../programme_contract_assessment_2026-09-09.md) for interpretation
and the [resolution document](../programme_conflict_resolution.md) for required work.

- `results.json`: metrics, environment, working-tree status, loader observations
  and input stability result.
- `input_manifest.csv`: hashes and size/mtime of 653 inputs, including relevant
  source code, current overrides and the CSVs used. This identifies the observed
  state; it does not archive or certify all pipeline dependencies.
- `quarter_profile.csv`: thirteen saved-cohort quarter summaries.
- `obligation_frame.csv`: all 910 fund-quarter slots, eligibility unadjudicated.
- `correction_instances.csv`: 251 JSON records with path eligibility, scope,
  selector/payload and target disposition. Eligibility is not successful application.
- `queries.sql`: executed DuckDB inventory queries; includes setup statements.
- `audit.py`: exact collector source. It writes only beside itself; preserve this
  evidence by copying the collector to a new session scratch directory before use.

To reproduce against the then-current saved inputs, run from the repository root
in PowerShell (change the session suffix if this directory already exists):

```powershell
New-Item -ItemType Directory -Path scratch/2026-09-09_contract_recheck
Copy-Item -LiteralPath docs/production_stack/programme_contract_evidence_2026-09-09/audit.py -Destination scratch/2026-09-09_contract_recheck/audit.py
python scratch/2026-09-09_contract_recheck/audit.py
```

The collector expects the existing Python environment and DuckDB, cached inputs,
and a two-level `scratch/<session>/` location. It has a 240-second watchdog, bounded
query results, two threads, 1 GB DuckDB memory and no disk spill; no pipeline module
imports, network calls, production writes or baseline changes. It fails if a
pinned input changes size/mtime during the run. A rerun with different inputs is
a new assessment, not a reproduction of this saved state.
