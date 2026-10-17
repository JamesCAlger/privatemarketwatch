# Apollo regression batch 5 independent review

Date: 2026-10-17. Reviewer: `/root/apollo_investigation_reviewer`.

Compared completed sandbox `ao_rg5` with accepted historical sandboxes `tnxc` (26North, CIK 0001950976) and `atxc` (Antares, CIK 0001976336). This bounded review used read-only artifacts and code/history inspection. No builds, tests, network, source edits, gate changes or dispositions were performed. Apollo's hashed fund report was not changed.

## Result

All reported differences in these two funds are signed-zero representations. **No changed numeric magnitude, missing/present transition, or source-fact state/currency was found in the complete changed populations.** This does not certify all holdings or resolve earlier regression findings.

| Fund | Field | Changed rows | Historical to current | Exact numeric equality |
|---|---|---:|---|---:|
| 26North | pct_of_net_assets | 57 | -0.0 to +0.0 | 57/57 |
| Antares | fair_value | 44 | +0.0 to -0.0 | 44/44 |
| Antares | pct_of_net_assets_calculated | 44 | +0.0 to -0.0 | 44/44 |
| Antares | cost | 12 | +0.0 to -0.0 | 12/12 |
| Antares | cost_reported | 12 | +0.0 to -0.0 | 12/12 |
| Antares | src_facts | 53 | Raw monetary signed-zero strings | 53/53 |

The 53 source-fact rows contain 56 changed properties: 44 `_financial_fair_value.raw` and 12 `_financial_cost.raw`; three rows contain both. Each is exactly `"0.0"` to `"-0.0"`. Parsed JSON comparison verified all other properties unchanged. Decimal comparisons verified exact numeric equality, rather than applying a tolerance. Thus these differences do not alter the corresponding FV, cost or NAV-percentage arithmetic.

## Independently verified boundary and mechanism

Joined final holdings by immutable `row_id`. For every changed source field, then joined each sandbox's raw `bdc_holdings.parquet` by CIK, accession and source context. All joins were complete and one-to-one for this population.

- All 57 26North raw percentage values are already -0.0 in tnxc and +0.0 in ao_rg5.
- All 44 Antares raw fair values are already +0.0 in atxc and -0.0 in ao_rg5.
- All 12 Antares raw costs are already +0.0 in atxc and -0.0 in ao_rg5.

The sign differences therefore precede unified staging and the Apollo `extracted_industry` correction allowlist. Financial finalization propagates present cost to both `cost` and `cost_reported`, retains raw monetary strings in source facts, and computes `pct_of_net_assets_calculated` as FV divided by compatible net assets times 100 (`pipeline/financial_conventions.py`). This explains the downstream families of signed-zero differences without a changed monetary value.

Examples permitting direct artifact checks:

- 26North `ROW-2f2d77147f057d08`, Baxter Planning Systems LLC, 2025-06-30, accession `0000950170-25-104137`, context `C_7cde2847-7255-446e-8911-30baedf74e52`: raw and final percentage -0.0 to +0.0.
- Antares `ROW-4f09bfdac2aa0b9b`, Ampirical Solutions LLC, 2026-06-30, accession `0001193125-26-349158`, context `C_286aba1e-aea1-43f4-91ad-cfc16ba752c0`: raw FV string +0.0 to -0.0, state remains explicit_usd and currency USD.
- Antares `ROW-a0362b71b65a3b5b`, Blades Buyer Inc, 2026-06-30, same accession, context `C_3cad61ba-6ff9-49dd-93dd-bcea18805e3b`: raw cost string +0.0 to -0.0, state remains present.

The exact earlier conversion/serialization operation that changed raw zero signs was not isolated. This review does **not** attribute it to a particular commit or claim the historical/current source artifacts are byte-identical. Recent wrapper commits 325bdfa and 0f45ad1 were inspected but do not by themselves establish the cause of these sign representations. Confidence is high for numeric equivalence and the pre-staging boundary; upstream sign-origin attribution remains limited.

## Evidence and scope

Reproducible bounded diagnostics: `scratch/fund_runs/apollo_rg5_diagnose.py/.log` records every changed row, field, source accession/context and numeric comparison; `scratch/fund_runs/apollo_rg5_boundary.py/.log` verifies all raw joins and all 53 parsed JSON comparisons. Scripts cap changed populations below 100 rows per field and use memory-limited DuckDB. No rows were sampled in these comparisons.

Root's regression comparison reports the other five funds unchanged, with no new outstanding findings, added/deleted rows or lost ties in this batch. Those broader checks were not independently repeated here. Root's corrected campaign total is **48 funds: 34 UNCHANGED and 14 MOVED**; MOVED includes representational differences and must not be equated with 14 financial regressions.

Prior unexplained Asurion classification, newly visible KKR convention findings, classification changes and full-suite failures remain separate unresolved campaign outcomes. This batch's numeric-equivalence result does not clear them or authorize acceptance. All diagnostic processes exited; writes stopped after this report.
