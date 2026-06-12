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

All 39 original queue entries have wrappers. New agents must claim work through
the shared claim helper so parallel sessions do not choose the same CIK.

Claim the next unwrapped BDC before profiling:

```bash
python scripts/bdc_wrapper_worklist.py --next --agent "<agent-name>"
```

The helper derives the queue from
`data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json`, excludes
CIKs that already have wrapper JSON files, excludes entries without holdings
data, and prioritizes current source-reconciliation blockers before holdings
row count. It writes `data/output/bdc_wrapper_claims.json` under an atomic
`.lock` file so multiple agents can claim different CIKs safely.

Useful commands:

```bash
python scripts/bdc_wrapper_worklist.py --stats
python scripts/bdc_wrapper_worklist.py --list --limit 20
python scripts/bdc_wrapper_worklist.py --done <CIK> --agent "<agent-name>"
python scripts/bdc_wrapper_worklist.py --release <CIK> --agent "<agent-name>"
```

Only mark a CIK `done` after the wrapper exists and deterministic validation
has been run. Use `--release` if the claim cannot be completed.

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
- **Do not run SEC downloads directly.** All raw data is cached by default. If missing BDC HTML evidence is explicitly needed, use only the audited guard script, e.g. `python scripts/download_missing_bdc_html.py --cik <CIK> --missing --max-downloads 10 --agent "<agent-name>" --reason wrapper_evidence`. This script validates the CIK/accession against `data/output/bdc_filings_index.csv`, enforces cross-process SEC throttling, writes atomically to `data/raw/filings/bdc_html/`, and appends receipts to `data/output/sec_download_manifest.jsonl`.
- **Validate with the final unified oracle before declaring success.** Visual plausibility is not evidence.
- **Do not hide failed oracle status.** Residual blockers are valid outcomes and must be documented.
- **Do not promote dispatch-only wrappers as extraction fixes.** They classify identifiers but may not change final holdings extraction.
- **Run `--match` before declaring a wrapper production-clean.** A wrapper that passes the unified oracle but has >10% D_fuzzy fallback (J03 fail) produces unstable position IDs across quarters, which corrupts index returns.
- **Use `matching_diagnostic.{CIK}.csv` to debug high fuzzy rates.** The `key_diff_summary` column shows exactly which tokens differ between begin and end position keys.
- **Position keys must be issuer-specific.** Generic keys like `"senior secured first lien term loan"` will be rejected by the B1b strong-key filter.
- **Review C/D/E match quality after J01/J03 stabilization.** Use `match_triage.{CIK}.csv` to identify flagged pairs. Work highest FV first. Prefer wrapper config fixes over per-pair overrides. Each override must have mechanism, evidence, confidence >= 0.70, and residual_risk.
- **Do not write overrides for issues fixable by wrapper config.** If a volatile position key token causes D_fuzzy fallback, fix `canonical_strip_re` instead of overriding individual pairs.
- **Override confidence thresholds:** reject requires >= 0.80, force_pair requires >= 0.85.
