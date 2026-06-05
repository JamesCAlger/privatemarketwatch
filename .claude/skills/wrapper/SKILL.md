---
description: Create or update a BDC XBRL wrapper JSON for a CIK
argument-hint: [CIK|next] [profile|create|validate|update]
allowed-tools: Bash Read Write Edit Grep Glob
---

# BDC XBRL Wrapper Skill

Build, validate, or update per-CIK wrapper JSON files that control how the pipeline classifies and extracts structured fields from XBRL investment identifiers.

**Usage:** `/wrapper [CIK|next] [mode]`

Modes: `profile` (default), `create`, `validate`, `update`

If the user does not specify a CIK, choose the next unprocessed CIK from the priority queue below.

---

## Architecture Context

A **wrapper** is a deterministic, versioned configuration mapping one filer's idiosyncratic XBRL identifier layout into clean structured records. The two-speed split is non-negotiable:

- **Hot path (per row):** deterministic, frozen, fully traceable. No LLM.
- **Edge (per new CIK or drift):** agent generates or repairs a wrapper, gated by deterministic verifiers.

Wrappers live at `data/overrides/bdc_xbrl_wrappers/{CIK}.json` and conform to `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.

There is **one wrapper per CIK** (no per-quarter versioning). Format drift across quarters is handled by broadening prefix rules, adding fallback patterns, or adding identifier parser config.

### Success contract

- **Schema validation passes** means the JSON is syntactically valid.
- **Wrapper classifier tests pass** means sampled identifiers classify as intended.
- **Promotion gate passes against final unified holdings** means the wrapper is production-clean.
- **J01 position key stability >= 70% B1b** means the wrapper's position keys are stable across quarters.
- **J03 fuzzy fallback rate <= 10%** means position keys aren't falling through to expensive fuzzy matching.
- **Raw oracle failures remain visible** even when an accepted soft-gate exception changes the effective promotion verdict.
- **Oracle fails** means the wrapper is partial unless residuals are explicitly documented, accepted, and only affect waiveable soft gates.

Do not describe a wrapper as complete because visual samples look plausible.

### Dispatch vs staging vs parser

- **`dispatch`** classifies source identifiers for reconciliation diagnostics. A dispatch-only wrapper may reduce ambiguity but may not improve final extraction.
- **`identifier_parser`** drives structured field extraction for identifiers that encode country, industry, issuer, instrument, rate, or maturity.
- **`staging`** handles custom extraction when generic parser logic is not enough.

---

## Priority Queue

FV-ordered queue for next unprocessed CIK. Basis: latest-quarter BDC FV, measured 2026-06-04.

| Priority | CIK | Entity |
|---:|---|---|
| 1 | 0001838126 | HPS Corporate Lending Fund |
| 2 | 0001837532 | Apollo Debt Solutions BDC |
| 3 | 0001930087 | Golub Capital Private Credit Fund |
| 4 | 0001872371 | Oaktree Strategic Credit Fund |
| 5 | 0001851322 | North Haven Private Income Fund LLC |
| 6 | 0001742313 | Monroe Capital Income Plus Corp |
| 7 | 0001859919 | Barings Private Credit Corp |
| 8 | 0001869453 | Blue Owl Technology Income Corp. |
| 9 | 0002031750 | Ares Core Infrastructure Fund |
| 10 | 0001913724 | TPG Twin Brook Capital Income Fund |
| 11 | 0001993402 | Antares Strategic Credit Fund |
| 12 | 0001950803 | Stepstone Private Credit Fund LLC |
| 13 | 0001930679 | KKR FS Income Trust |
| 14 | 0001901164 | T. Rowe Price OHA Select Private Credit Fund |
| 15 | 0001825384 | Stone Point Credit Corp |
| 16 | 0001916099 | Diameter Credit Co |
| 17 | 0001702510 | Carlyle Credit Solutions, Inc. |
| 18 | 0001901612 | Golub Capital BDC 4, Inc. |
| 19 | 0001911066 | Nuveen Churchill Private Capital Income Fund |
| 20 | 0001902649 | BlackRock Private Credit Fund |
| 21 | 0002037804 | New Mountain Private Credit Fund |
| 22 | 0001989817 | HPS Corporate Capital Solutions Fund |
| 23 | 0001885968 | T Series BDC LLC |
| 24 | 0001899017 | Bain Capital Private Credit |
| 25 | 0001925531 | New Mountain Guardian IV BDC, L.L.C. |
| 26 | 0002049733 | Blackstone Private Real Estate Credit & Income Fund |
| 27 | 0001634452 | AB Private Credit Investors Corp |
| 28 | 0001975736 | KKR FS Income Trust Select |
| 29 | 0002083477 | APS BDC, LLC |
| 30 | 0001959604 | Jefferies Credit Partners BDC Inc. |
| 31 | 0002012139 | Fortress Private Lending Fund |
| 32 | 0001976336 | Antares Private Credit Fund |
| 33 | 0001899996 | Fidelity Private Credit Co LLC |
| 34 | 0002052152 | Apollo Origination II (Levered) Capital Trust |
| 35 | 0001772704 | Goldman Sachs Private Middle Market Credit II LLC |
| 36 | 0001965934 | Overland Advantage |
| 37 | 0002011498 | AGL Private Credit Income Fund |
| 38 | 0001766037 | NMF SLF I, Inc. |
| 39 | 0001919369 | VISTA CREDIT STRATEGIC LENDING CORP. |

---

## Mode Dispatch

Read the mode-specific doc for detailed instructions:

- **profile** (default): Read and follow `docs/wrapper/WRAPPER_PROFILE.md` (Steps 0-1).
- **create**: Read `docs/wrapper/WRAPPER_PROFILE.md` first (Step 1 profiling), then read and follow `docs/wrapper/WRAPPER_CREATE.md` (Step 2 + authoring pitfalls).
- **validate**: Read and follow `docs/wrapper/WRAPPER_VALIDATE.md` (Steps 3-6 + validation pitfalls).
- **update**: Read `docs/wrapper/WRAPPER_PROFILE.md` (re-profile), then `docs/wrapper/WRAPPER_CREATE.md` (modify), then `docs/wrapper/WRAPPER_VALIDATE.md` (validate).

---

## Guardrails

- **Do not add identifiers to aggregate_markers unless verified across all quarters.** A subtotal in one quarter may become a leaf in another.
- **Include truncation variants in prefix_rules.** Filers sometimes have off-by-one prefix truncation in XBRL (e.g. `IInvestment`, `nvestment`).
- **Test both leaf survival and aggregate filtering.** Every wrapper change needs at least one "this real position survives" and one "this subtotal is filtered" test.
- **Do not run SEC downloads.** All raw data is cached. Use `_prepare_bdc()` or `--fresh-bdc-staging` to rebuild from cache.
- **Validate with the final unified oracle before declaring success.** Visual plausibility is not evidence.
- **Do not hide failed oracle status.** Residual blockers are valid outcomes and must be documented.
- **Do not promote dispatch-only wrappers as extraction fixes.** They classify identifiers but may not change final holdings extraction.
- **Run `--match` before declaring a wrapper production-clean.** A wrapper that passes the unified oracle but has >10% D_fuzzy fallback (J03 fail) produces unstable position IDs across quarters, which corrupts index returns.
- **Use `matching_diagnostic.{CIK}.csv` to debug high fuzzy rates.** The `key_diff_summary` column shows exactly which tokens differ between begin and end position keys.
- **Position keys must be issuer-specific.** Generic keys like `"senior secured first lien term loan"` will be rejected by the B1b strong-key filter.
