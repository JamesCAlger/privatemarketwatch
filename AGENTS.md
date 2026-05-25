# AGENTS.md

Guidance for future Codex agents working in this repository.

## Mission

This project builds public-facing private markets indices from SEC regulatory filings. The most important product risk is not code neatness; it is publishing position, fund, classification, or return data that is materially wrong without knowing how wrong it is.

Treat the repository as a data product with a Python extraction/validation pipeline and a static Next.js frontend. Production engineering matters, but it should serve a measurable data-quality contract.

## Current Architecture

- Python pipeline modules live in `pipeline/`.
- Cached/raw SEC inputs live under `data/raw/`.
- Pipeline outputs live under `data/output/`.
- Frontend JSON exports live under `frontend/public/data/`.
- Next.js frontend source lives under `frontend/src/`.
- Tests live under `tests/`.
- Project context and historical decisions are in `CLAUDE.md`, `NEXT_STEPS.md`, and `docs/agentic_data_quality.md`.

Core commands:

```powershell
python -m pipeline.main --unified --validate
python scripts/rebuild_outputs.py
python scripts/rebuild_outputs.py --unified
python -m pipeline.main --export-frontend
pytest tests/
cd frontend
npm run build
```

## Non-Negotiable Data Semantics

- The index is position-level, not borrower-level. Do not aggregate distinct loan tranches, equity co-investments, preferred shares, warrants, or fund interests into one borrower constituent unless a downstream analytic explicitly asks for borrower exposure.
- `private_markets_holdings.csv` is the central unified holdings artifact.
- Frontend JSON is derived data. If frontend numbers look wrong, investigate the CSV/export pipeline before patching frontend JSON by hand.
- BDC XBRL data is strongest from roughly 2022 onward. Pre-XBRL HTML extraction depends on per-CIK templates and validation.
- Consumer/marketplace lending CIKs with opaque individual loan IDs are intentionally excluded from index-facing unified outputs because they inflate row counts while contributing little FV.
- Comparative-period BDC rows can be legitimate prior-period facts, not duplicates. Confirm `period`, `report_date`, accession, and dimension path before removing them.

## Guardrails

- Do not make unrequested network calls to SEC EDGAR or third-party sites. Use cached data unless the user explicitly asks for downloads.
- Do not bypass `pipeline.edgar_client.EdgarClient` or its rate limiting.
- Do not run broad extraction/download commands casually. `--holdings`, `--nport`, `--financials`, and exhaustive discovery can be slow and may hit external services.
- `pytest tests/` can overwrite output CSVs with fixtures. After running tests, rebuild production outputs before treating `data/output/` or `frontend/public/data/` as production data.
- Do not use pandas `.apply()`, `.iterrows()`, or row-level Python loops on large holdings datasets. Use DuckDB SQL or vectorized operations.
- Keep log output ASCII-safe. Windows console encoding has previously failed on Unicode punctuation and box drawing.
- Do not edit generated frontend JSON directly unless the task is explicitly about generated artifacts. Prefer fixing `pipeline/export_frontend.py` or upstream CSV generation.
- Do not revert user changes. This repository often has a dirty worktree with active experiments, generated data, and ad-hoc scripts.

## Anti-Sycophancy Requirement

The user has finance and data-science context, but not necessarily software engineering context. Future agents must give professional engineering judgment, not validation of every premise.

Required behavior:

- Challenge requests that would make data quality less measurable, make validation weaker, or increase silent corruption risk.
- State when a proposed shortcut is unsafe, even if it seems to satisfy the immediate request.
- Separate "what the user asked for" from "what the system needs next" when they differ.
- Prefer evidence from source filings, deterministic reconciliation, tests, and measured validation outputs over intuition or narrative fit.
- Do not overstate confidence. If a metric is only a proxy for correctness, call it a proxy.
- Treat failed validation or unresolved ambiguity as a valid outcome. Do not force data to pass by widening filters, adding overrides, or suppressing checks without a mechanism and evidence.

In this project, politeness means being direct about risk.

## Priority Judgment

There are two competing next-step tracks:

1. Refactor the research-oriented codebase toward production code.
2. Improve frontend data accuracy and/or publish metrics that measure remaining inaccuracy.

The better next step is usually track 2 first.

Reason: refactoring before the data-quality contract is explicit can preserve wrong behavior behind cleaner abstractions. This codebase's main risk is long-tail filing idiosyncrasy: subtotal leakage, affiliation-axis duplication, identifier parsing variation, fund taxonomy errors, and rate-scale ambiguity. A cleaner module boundary does not solve those unless the target behavior is pinned down by source reconciliation and validation gates.

Refactoring is still necessary, but it should be driven by the data-quality architecture:

- Build or strengthen reconciliation first.
- Move per-CIK quirks out of global code where possible.
- Add tests around the measured behavior.
- Then refactor the implementation while preserving those gates.

## Best Next Discussion

After this file, the next conversation should decide:

- Whether any urgent production refactor blocks data-quality work.
- Which validation gaps most directly affect public frontend trust.
- Which human validation loops can be replaced by constrained agent loops.

If choosing track 2, the recommended sequence is:

1. Define a public data-quality contract: freshness, coverage, source reconciliation, GAV reconciliation, classification confidence, and known exclusions.
2. Build deterministic source reconciliation for BDC holdings by CIK-quarter against cached XBRL facts.
3. Add fund-level metadata/strategy validation so holdings classification can be checked against independent fund identity signals.
4. Introduce per-CIK corrections as audited JSON/config, not growing global keyword lists.
5. Use agents only on validation residuals, with mandatory evidence, mechanism, confidence, and explicit escalation.
6. Surface quality tiers in frontend data: verified, preliminary, under review, stale.

## Agentic Data Quality Design

Agents should be subroutines inside a deterministic pipeline, not autonomous owners of the truth.

Preferred architecture:

- Layer 1: global deterministic transformation rules in Python/DuckDB.
- Layer 2: per-CIK corrections with schema, mechanism, evidence, confidence, and audit trail.
- Layer 3: fund-level metadata and strategy overrides grounded in N-CEN, prospectus language, or other source evidence.
- Validation layer: independent checks that the agent cannot satisfy by editing its own output.

Strong validation gates:

- Source reconciliation against cached XBRL or source filing facts.
- GAV/total-assets reconciliation against independent fund-level data.
- Cross-quarter position stability.
- Cross-layer fund strategy versus holdings mix.
- Classification cross-reference checks.
- Yield/rate sanity checks against fund income.

Weak validation checks are useful as flags, not gates:

- Generic pct-of-net-assets range checks.
- Null/fill-rate checks without source reference.
- Internal-only anomaly scores.
- "Metric improved" comparisons without a mechanism.

Every agent-authored correction should answer:

- What changed?
- Why is this the right mechanism?
- Which source evidence supports it?
- What metric changed before and after?
- What is the confidence?
- What residual risk remains?

Escalation is better than pretending. If no mechanism is found after bounded attempts, document the hypotheses tested and stop.

## Data Investigation Practice

For ad-hoc investigations:

- Save lasting findings to `data/output/data_investigation_results.md` or a project doc, not only to temp scripts.
- Include the question, data sources, commands or queries used, conclusion, and residual uncertainty.
- Do not promote a one-off pattern to a global rule without checking false positives across other CIKs.
- Prefer CIK-quarter scoped analysis before global changes.

Temporary scripts are acceptable for exploration, but production behavior belongs in `pipeline/` with tests.

## Implementation Guidance

Use existing patterns:

- DuckDB SQL for large CSV transformations.
- Small pandas DataFrames only for summaries, tests, and narrow in-memory operations.
- `pipeline.config` for paths and shared constants.
- `scripts/rebuild_outputs.py` for cached-data rebuilds.
- `pipeline.export_frontend.export_all()` for frontend JSON.
- Existing test helpers and fixture style in `tests/`.

When changing data logic:

- Add focused tests for the exact failure mode.
- Include at least one false-positive test when adding filters or keyword rules.
- Check whether the change belongs in global rules or per-CIK configuration.
- Rebuild affected outputs from cached data.
- Export frontend JSON if public UI data changes.

When changing frontend:

- Keep it consistent with the existing Next.js/Tailwind/Recharts app.
- Frontend should explain data status through metrics and provenance, not marketing copy.
- Do not hide uncertainty. Public trust is improved by showing validation status and known limitations.

## Verification Expectations

Choose verification proportional to the change:

- Pure docs change: no tests required.
- Small parser/classification change: targeted `pytest` file.
- Unified holdings change: targeted tests plus `python -m pipeline.main --unified --validate` or `python scripts/rebuild_outputs.py --unified` when practical.
- Export change: run `python -m pipeline.main --export-frontend` and inspect changed JSON shape.
- Frontend TypeScript/UI change: run `npm run build` in `frontend/`.

Always report what was and was not run.

## Commit Guidance

When asked to commit changes, include both a concise subject and a reasonably sized commit body. The body should explain what changed, why it changed, and what verification was run or skipped. Keep it focused; do not paste long command output, generated diffs, or unrelated investigation notes into the commit message.

## Files Worth Reading First

- `CLAUDE.md`: current state, contracts, schemas, and operational warnings.
- `docs/agentic_data_quality.md`: proposed agentic validation architecture.
- `pipeline/unified_holdings.py`: central holdings construction and classification.
- `pipeline/validate_holdings.py`: validation suite and output files.
- `pipeline/export_frontend.py`: public JSON aggregation.
- `pipeline/main.py`: orchestration and command flags.
- `pipeline/config.py`: paths, SEC settings, CIK exclusions, frontend cutoff.
- `tests/test_unified_holdings.py`: regression coverage for holdings rules.
- `tests/test_validate_holdings.py`: validation behavior.
- `frontend/src/lib/data.ts` and `frontend/src/lib/types.ts`: frontend data contract.

## Current Product Risk Register

Known high-value risks to keep in mind:

- Subtotal/category rows leaking into position-level holdings.
- Duplicate facts from multiple XBRL dimension paths.
- `pct_of_net_assets` inflation from duplicate dimension paths or wrong denominator.
- Fund-level strategy/taxonomy errors that holdings-level rules cannot catch.
- N-PORT source fields that are mislabeled by filers.
- Rate scale ambiguity.
- Entity resolution undercoverage, especially N-PORT.
- Public frontend charts implying precision that validation does not support.

Do not treat a visually plausible dashboard as evidence that the data is correct.

## Production Refactor Direction

When refactoring does become the priority, the safest direction is:

- Separate extraction, normalization, correction, validation, and export boundaries.
- Move filer-specific quirks into data/config with schemas.
- Make validation outputs first-class artifacts consumed by frontend and agents.
- Keep global rules small, heavily tested, and evidence-backed.
- Preserve CLI behavior unless deliberately changing the operator workflow.

Avoid large aesthetic rewrites. The productive refactor is one that reduces silent-data-corruption risk or makes validation easier to reason about.
