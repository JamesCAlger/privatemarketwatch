# Rule-authority evidence, 2026-09-09

Read the [assessment](../programme_rule_authority_assessment_2026-09-09.md) for conclusions and limitations. `run1/` is the retained complete run, produced at 19:41 UTC. Earlier development runs are disposable under `scratch/2026-09-09_programme_rules/`.

Reproduce against the current working tree from the repository root, using a **new** output directory:

```powershell
python scripts/programme_rules/audit.py --output scratch/YYYY-MM-DD_programme_rules/replay1
```

The [audit](../../../scripts/programme_rules/audit.py) and [family definitions](../../../scripts/programme_rules/families.tsv) are pinned in `input_manifest.csv`. Reproduction against changed code/inputs is a new observation, not a replacement for `run1/`. Hashes identify local files; this bundle does not contain a full restorable source checkout.

| Artifact | Purpose |
|---|---|
| `run_summary.json`, `input_manifest.csv`, `worktree.json` | Execution identity, source/data hashes, versions, completion and bounded drift checks. |
| `rule_authority_register.csv`, `embedded_code_sites.csv` | Human-curated semantic families and mechanically located source candidates; not a certified count of active business rules. |
| `rule_assets.csv`, `wrapper_sections.csv`, `loader_results.json` | Asset scope, eligibility/schema findings, section pointers and actual read-only loader counts. |
| `control_inputs.csv`, `control_constants.json` | Saved lookup/control presence/counts and current source constants. |
| `runtime_probes.json`, `runtime.log`, `fixtures/` | Ten synthetic observations, logs, exact fixture payloads and isolated CSV/Parquet outputs. Values are not production metrics. |

The script returns success when the diagnostic completes with resolved function references and no measured drift. It does **not** return product acceptance: reproduced defects are expected observations. Maximum 240 seconds, 20 fixture rows per replay and 10,000 output inventory rows. CSV controls over 64 MiB receive metadata-only inspection. No production rebuild or network access is part of the audit.
