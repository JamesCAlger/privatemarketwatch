# Overnight specification evidence

Read the [closeout decision pack](../programme_spec_closeout_2026-09-09.md) first. These are preparation/development results, not an approved production release.

| Evidence | Contents |
|---|---|
| `units/`, `unit_resolution/` | Document-scoped unit parsing, case normalization, currency/field/quarter inventories and unresolved observations |
| `currency_cases/` | Cached-source hashes, literal cells, unit conflicts and supporting notes |
| `review/packet_dispositions.csv` | All 61 pilot packet dispositions with explicit source/roster/anchor limitations |
| `review/new_development_rosters.json` | Complete 26North four-position and Golub one-money-market-position source rosters |
| `review/legacy_label_decisions.json` | Twenty proposals preserving original labels, exact source rows and uncertainty |
| `review/boundary_examples.json`, `review/pik_native_examples.json` | Actual zero/negative, PIK, identity/scope and source-duration examples |
| `baseline/` | Rebuilt-input identity, exact CSV/Parquet typed comparison, quarter/obligation baseline, new-roster results and numerical proposal |
| `rule_replay/` | Full B2 pre/post fund-quarter accounting, per-rule footprints, observed overlaps and reversed-order comparison |
| `identity/` | Exposed mg3 packet census, source-row joins, synchronized identity scores and durable-ID migration example |
| `viewer/` | Offline viewer, source/cell/rendition identities and actual browser/performance results |
| `restore_proof.json` | Physical restoration and hash verification of the real completed bundle |
| `stage_compatibility.json`, `original_input_preservation.json` | Exact composed-stage correspondence and preservation of frozen production/control/reference inputs |
| `artifact_manifest.json` | Final retained evidence identities and local/compressed asset restoration information |

The scripts live in `scripts/programme_closeout/`. Existing evaluator primitives remain in `scripts/programme_reference/`. Commands run from the repository root. See the work record and manifests before starting any job; do not recreate a completed attempt in place.

The frozen candidate is `data/programme/candidates/spec-close-20260909-v2/`. Successful stages are `unified-01`, `identity-02` and `evidence-01`; earlier failed/stopped attempts are deliberately retained. Each successful stage has its own input and result identities. The native cached source files and original gold remain unchanged.

Large raw unit CSVs and the four full filing renditions are reproducible local assets. Compressed unit CSV companions retain decompressed hashes; the viewer builder regenerates passive filing renditions from the pinned local source cache. No network call is needed to use the local viewer. The archived manifest distinguishes evidence files from these generated copies.

The prototype's direct source links are HTML, not PDF. Inferred values have separately labelled decision/business evidence and may remain unresolved. The Forterro research assignment is explicitly provisional and excluded from independent accuracy gold.
