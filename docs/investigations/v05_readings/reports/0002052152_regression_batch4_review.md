# Apollo regression batch 4: bounded independent diagnosis

2026-10-16; reviewer `/root/apollo_investigation_reviewer`. Read-only scratch diagnostics. No builds, tests, network, pipeline/input edits, dispositions, or gate changes.

## Classification: 27 of 27 reproduced

CIK 0001634452, ao_rg4 versus abxf: 27 subindustry and 27 sector differences, all Amercare Royal rows. Historical null becomes Health Care Services; no labels lost. Selected all 31 rows in affected issuer families, reconstructed filed names from raw rows joined by CIK/accession/context, and replayed isolated historical (`c8cf047^`) and current GICS functions.

The two company caches are byte-identical: 32,270,986 bytes, SHA256 `465fb2fdd6e9a5aff88394860603bde53df1804f4ef6c5d4a7eb89ef87f67097`.

Both functions reproduce all 27 current labels with current canonical name `AmerCareRoyal, LLC`. Both reproduce all 27 historical nulls with historical canonical name `Amercare Royal LLC`. Thus the necessary changed input is the canonical entity name; the c8cf047 precedence change does not explain these differences by itself. Current entity resolution resolves the build's population before GICS (`_resolve_entities_in_build` in unified_holdings), making the historical single-fund/current batch population a relevant dependency. No new entity-resolution code commit is needed to reproduce this result. The precise entity-clustering membership decision was not replayed or certified. The Apollo correction-field allowance is not exercised by these isolated GICS replays.

All 27 old/new sectors agree with the corresponding hierarchy mapping. This is high-confidence attribution of the changed GICS lookup input, not an independent judgment that Health Care Services is the correct business classification for Amercare Royal. No legacy classification changes are accepted here.

Evidence: `apollo_gics_rg4.py`, `.log`, `apollo_gics_rg4_rows.json`, `apollo_rg4_canonical_replay.py/.log`, and `apollo_rg4_facts.py/.log` in this directory.

## Source facts: ten exact numeric equivalents

Parsed every changed source-fact JSON object; only `_financial_fair_value.raw` differs. Currency, state and every other parsed key are unchanged. Decimal comparisons verify exact numeric equality, including negative and zero values. Every difference adds `.0` to an integer string.

| CIK / historical sandbox | Row | Issuer | Quarter | Raw value before `.0` |
|---|---|---|---|---:|
| 0001899017 / bnxd | ROW-9e4961c64b0a6e7f | KAMC Holdings Inc | 2025-09-30 | 943000 |
| 0001899017 / bnxd | ROW-5347b4c2fbf8c330 | KAMC Holdings Inc | 2025-09-30 | 32556000 |
| 0001899017 / bnxd | ROW-d76dac801d193f69 | Spindrift | 2025-12-31 | 1574000 |
| 0001899017 / bnxd | ROW-c5e88b7cee9a7f51 | Spotless Brands | 2025-12-31 | 9618000 |
| 0001975736 / ksxf | ROW-afc5e48d2358a51b | Community Brands Inc | 2024-09-30 | -2000 |
| 0001975736 / ksxf | ROW-4aaae01ba847975f | Community Brands Inc | 2024-09-30 | -3000 |
| 0001975736 / ksxf | ROW-e7e15a97d2e4db51 | Discover Financial Services | 2025-06-30 | 0 |
| 0001975736 / ksxf | ROW-26b15a5f6dde499b | EW Scripps Co/The | 2025-06-30 | 0 |
| 0001975736 / ksxf | ROW-672c07b7d7c7bc7b | BGB Group LLC | 2026-03-31 | 0 |
| 0001975736 / ksxf | ROW-ef1d32247f31763a | Bond Aviation Holdings LLC | 2026-03-31 | 0 |

This establishes equivalent monetary provenance values, not the historical serialization commit that introduced the formatting. No specific serialization commit is asserted. Parent reports other seven funds unchanged and no new outstanding findings, rows or lost ties; those broader checks were not duplicated here.

## Prior Asurion residual remains unresolved

Batch 3 MidCap `ROW-9c70279521a746a1` remains unexplained. The historical/current raw BDC row is identical, and historical-canonical replay still produces a label where historical output is null. Bounded review confirms `_issuer_name_filed` is captured after promoted corrections and `_issuer_from_identifier`, then strips and entity resolution precede GICS. A staging-only filed-name reconstruction does not certify that exact historical entry frame. No matching MidCap Asurion row correction was found in the current row-corrections table; that is not proof of the complete historical promoted-input state.

Resolving this requires recovering/reconstructing the exact historical GICS-entry frame and all preceding applicable transformations. This task did not do a historical rebuild and does not claim a cause. Preserve the batch 3 one-row unexplained classification and four KKR unresolved convention findings. Their evidence remains in `apollo_regression_batch3_review.md`.

All bounded diagnostic commands completed. Writes stopped after this note. No acceptance or fixes performed.
