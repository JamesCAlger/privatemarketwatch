# Isolated programme pilot evidence

See [findings and numerical proposal](../programme_measurement_pilot_2026-09-09.md).
This is a development/calibration bundle, not a promoted acceptance benchmark.
Original dated reference evidence and production artifacts are preserved.

| Files | Purpose |
|---|---|
| `pilot_summary.json`, `quarter_pilot_status.csv`, `pilot_status.csv` | Actual results, all 13 quarter denominators, all 61 packet dispositions and explicit unavailable metrics |
| `obligations_v2.csv`, `quarter_denominators.csv` | Updated 910-slot assessment: Fortress eligible; original frozen version retained elsewhere |
| `source_documents.csv`, `source_rows.csv.gz`, `source_facts.csv.gz`, `source_tables.csv` | Source-only candidates, actual document hashes/locators, fact values and precision; includes totals/repeats and is not a certified roster |
| `source_anchor_candidates.csv`, `source_units.csv` | Unreviewed anchor inventory and unit mappings used for probes |
| `tag_copy_fields.csv.gz`, `tag_copy_totals.csv`, `tag_copy_summary.csv`, `tag_copy_discrepancies.csv` | Complete probe outcomes, aggregate counts and material/unassessable cases; not population financial accuracy |
| `reviewed_roster_result.json`, `lord_reviewed_roster.json`, `lord_full_schedule.json` | Two source-reviewed development rosters, including Lord's six untagged FV dashes |
| `reviewed_primary_anchors.csv`, `reviewed_anchor_results.json`, `pilot_candidate_totals.csv` | Source-selected development totals and signed published comparison; raw subsidiary-excluded sum is only a diagnostic |
| `legacy_label_comparison.csv`, `legacy_label_summary.csv`, `review_case_sources.json` | Existing tail-label comparison using the old 1% scorer, plus original rows supporting reference-conflict dispositions; no label edits |
| `esdec_candidate_rows.csv`, `explicit_zero_cost_candidates.csv` | Development continuation/currency examples; the narrow joined literal-zero-cost search is empty, not proof of no source zeros |
| `gap_xml_documents.csv`, `gap_xml_facts.csv`, `supplemental_input_manifest.csv` | 77-document comparative search and additional raw-source hashes |
| `input_manifest.json`, `verification.json`, `run_identity.json`, `worktree_status.txt`, `artifact_manifest.json` | Candidate/code identities, preserved-input checks, test result, limits and archived artifact integrity |
| `semantic_diff_report.json`, `semantic_backstop_result.json`, `semantic_only.log` | Completed five-artifact comparison to active baseline; the full manifest byte scan timed out |

Large CSVs are deterministically gzipped to keep the tracked bundle compact.
DuckDB `read_csv` reads them directly. No rows were removed by compression.
`artifact_manifest.json` hashes the archived files, excluding itself.

Reproduce in a fresh `scratch/YYYY-MM-DD_<topic>/` directory inside this repo:

1. Copy `collect_sources.py`, `gap_sources.py`, `source_profiles.py`,
   `review_cases.py`, `complete_lord_roster.py` and `summarize_pilot.py` there.
   These bounded collectors write beside themselves. **Do not execute these
   copies inside the dated evidence directory.**
2. Run `collect_sources.py`, `gap_sources.py` and `source_profiles.py`. The source
   collector reads the original 61-cluster manifest and validates its checkpoint
   against source stats and reader-code hash. Original input hashes must match
   before interpreting this as a replay.
3. From the repo root run
   `python -m scripts.programme_reference.measure_pilot --source-dir scratch/<session>/sources --output-dir scratch/<session>/results`.
   This pins and compares the saved candidate. It does not rebuild production.
4. Run `review_cases.py`, `complete_lord_roster.py`, then `summarize_pilot.py`.
   Explicit development row selections/dispositions are source-reviewed decisions,
   not new global extraction rules. Changed sources require renewed review.
5. For verification, use `python -m pytest tests/test_programme_reference.py -q`.
   `semantic_backstop.py` preserves the report under scratch; `--semantic-only`
   runs the existing module's five semantic comparisons, without the full byte
   scan. Read the recorded verification limits before interpreting results.

`archive_pilot.py` records how this specific bundle was assembled; it targets this
dated directory and is not a general replay step. Regenerate evidence into a new
dated bundle instead of overwriting an accepted reference. Code dependencies
are the existing local Python/DuckDB/lxml environment; no installation or network
access is required. The production scorer is imported only for its read-only
legacy-label comparison helper. Its promoted inputs/outputs remain unchanged.
