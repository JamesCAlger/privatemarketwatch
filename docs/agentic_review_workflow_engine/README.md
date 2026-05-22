# Agentic Review Workflow Engine

## Purpose

This repository now has several related manual and Codex-assisted review loops:

- GICS enrichment and aggregate-header flagging, documented in `docs/skill_architecture/gics_aggregate_skill.md`.
- Fund-strategy group review, implemented in `pipeline/fund_strategy_group_review.py`.
- Source reconciliation and CIK-quarter blocker review, supported by `pipeline/bdc_cik_validator.py` and the broader design in `docs/agentic_data_quality.md`.
- Constrained validation FAIL verification, planned in `docs/constrained_fail_verification_plan.md`.
- Future classification, enrichment, source-blocker, and remediation tasks that will have the same shape.

The goal is a reusable workflow engine rather than a new one-off harness for every review problem. A user should be able to define a review target by pointing to a rule, column, queue, or validation artifact. The system should then build immutable evidence bundles, run a masked calibration pilot, score the pilot against known labels or previously reviewed examples, and only then allow Codex instances to produce full-run verdicts or isolated pipeline/config patches.

The core pattern is:

1. Evidence bundle.
2. Blind calibration.
3. Structured verdict.
4. Isolated mutation path, when mutation is allowed.
5. Independent validation.
6. Human merge.

The engine should improve throughput without weakening the data-quality contract. Accuracy/F1 can authorize a larger run or a branch attempt; it must not authorize automatic merge into production outputs.

## Existing Patterns In The Repo

The current workflows share enough structure to justify a common abstraction, but they do not carry the same data risk.

| Workflow | Unit of Work | Output Artifact | Validation Strength | Mutation Model | Current Limitations |
|---|---|---|---|---|---|
| GICS harness | Entity or normalized issuer name batch | `company_gics_cache.csv`, `aggregate_header_flags.csv`, batch CSVs under `data/output/gics_skill_batches/` | Vocabulary checks, verdict/confidence enums, deduplication, later pipeline rebuild | Direct cache/flag updates through controlled merge script | Lightweight evidence requirements; direct artifact updates are acceptable for enrichment but insufficient for extraction remediation |
| Fund-strategy group review | Grouped candidate rows keyed by CIK, issuer, instrument, current/proposed classifications, rule, and mechanism | `data/output/fund_strategy_group_review/grouped_worklist.csv`, bundles, verdict JSON, summaries | JSON Schema validation, evidence bundle existence, required evidence for rule-gap verdicts | Review-only; no classifier, holdings, or frontend mutation | Good bundle/verdict precedent, but not yet a generic manifest-driven engine |
| Source reconciliation blockers | CIK-quarter or blocker row/group | Validation packets and residual artifacts such as source reconciliation blockers | Strong when grounded in cached source facts and GAV comparison; `bdc_cik_validator.py` separates strong, moderate, and context-only GAV gates | Not yet a full Codex queue/branch workflow | Strong validation artifacts exist, but remediation needs isolated branch/config discipline |
| FAIL verification | Validation issue row or CIK-quarter failure group | Planned verdict JSON under `data/output/fail_verification/verdicts/` | Strict schema, bundle hash, evidence references, no-mutation guardrails | Review-only during verification | Useful constrained-verdict design, but remediation is explicitly deferred |

The important difference is mutation risk. Direct agent-assisted cache edits can be reasonable for bounded enrichment when the merge script validates vocabulary, confidence, and deduplication, and when mistakes remain visible as classification quality issues. The same posture is unsafe for blocker remediation. Source blockers, GAV misses, duplicate dimension paths, parser defects, and validation FAILs can change which rows exist, their values, and whether public metrics look reconciled. Those changes need either deterministic merge from accepted verdicts or isolated code/config branches with independent validation gates.

## Proposed Reusable Workflow

A generic workflow should follow this lifecycle:

1. The user defines a workflow target: a validation rule, enrichment column, classification task, blocker queue, or residual artifact.
2. The system proposes a bundling strategy: grouping keys, evidence joins, priority score, gold-label source, masking strategy, and verdict schema.
3. Pilot bundles are generated from known-good, known-bad, or previously reviewed rows, with labels masked where calibration is being measured.
4. One or more Codex instances run the pilot and write structured verdicts.
5. Pilot scoring estimates label accuracy, macro/micro F1 where relevant, abstention quality, evidence quality, schema pass rate, and confident-wrong rate.
6. If thresholds pass, the full workflow runs.
7. For data-only workflows, a deterministic merger converts accepted verdicts into cache, config, or correction artifacts.
8. For pipeline-changing workflows, Codex works in an isolated branch or worktree and produces code/config/tests.
9. Independent validation gates decide whether the branch is merge-ready.
10. A human reviews and merges.

This keeps Codex as a bounded reviewer or patch author inside a deterministic system. It should not become the owner of truth. For unresolved cases, the correct output is an explicit unresolved verdict with evidence and residual risk, not a forced pass.

## Workflow Definition Manifest

The engine should eventually be manifest-driven. The manifest defines the task and its controls; generated worklists, bundles, verdicts, scores, and patch reports are immutable audit artifacts.

Recommended manifest fields:

| Field | Purpose |
|---|---|
| `workflow_id` | Stable identifier used in output paths and audit records |
| `description` | Human-readable purpose and risk boundary |
| `input_artifact` | Source CSV/JSON/report, such as a validation residual file or candidate table |
| `unit_of_review` | Row, entity, group, CIK-quarter, blocker group, or rule failure |
| `grouping_keys` | Columns used to aggregate rows into review units |
| `priority_score` | Sort or sampling score, usually fair value, materiality, severity, recency, or blocker count |
| `bundle_builder` | Script/function that materializes evidence bundles |
| `evidence_sources` | Required source artifacts, cached filings, validation outputs, and hashes |
| `gold_label_source` | Known labels or prior human-reviewed verdicts for calibration |
| `masking_rules` | Fields to hide in blind calibration |
| `verdict_schema` | JSON Schema for Codex outputs |
| `allowed_actions` | Review, recommend, deterministic merge, config patch, or pipeline patch |
| `mutation_mode` | `review_only`, `deterministic_merge`, `config_patch`, or `pipeline_patch` |
| `validation_commands` | Commands required before accepting outputs |
| `acceptance_thresholds` | Pilot and full-run thresholds |
| `merge_gates` | Required checks before merge or production use |
| `output_dir` | Root for worklist, bundles, verdicts, scores, summaries, and patch reports |

The manifest should not over-specify code that does not exist yet. Its job is to pin down review semantics, evidence, scoring, allowed actions, and merge gates before Codex instances start work.

## Bundle Design And Calibration

Bundle quality must be tested before scaling. A weak bundle teaches the agent to guess. A strong bundle gives enough evidence to decide, abstain, or escalate without hidden assumptions.

Required bundle principles:

- Include stable row/group identity and artifact fingerprints.
- Include the pipeline output and the source evidence, not just derived columns.
- Include enough source context for the requested decision.
- Include prior-quarter and current-quarter context when stability matters.
- Include fund-level context when holdings classification depends on fund strategy.
- Avoid leaking masked labels in calibration mode.
- Use stable evidence IDs that verdicts must cite.

Calibration should be stratified, not first-N:

- High fair value and high public-impact rows.
- Common easy cases.
- Edge cases and ambiguous cases.
- Different CIKs, sources, and mechanisms.
- Prior accepted corrections.
- Known bad or regression fixtures.
- Manual samples from unresolved rows after the first pilot if the pilot population is too easy.

Recommended pilot metrics:

- Label accuracy.
- Macro and micro F1 where class imbalance matters.
- Precision/recall for high-harm classes.
- Abstention quality: whether low-evidence cases are escalated instead of guessed.
- Evidence-reference validity.
- Schema pass rate.
- Confident-wrong rate.
- Downstream validation delta for remediation tasks.

Known-good calibration rows can be easier than unresolved production rows. The pilot score should therefore be treated as permission to proceed cautiously, not as proof that the full workflow is correct.

## Mutation And Branch Model

Agents may amend data artifacts or pipeline behavior only through an explicit mutation mode. Accuracy/F1 thresholds authorize the next controlled step; they do not authorize automatic production merge.

Mutation modes:

| Mode | Allowed Output | Appropriate Use |
|---|---|---|
| `review_only` | Verdict JSON only | FAIL verification, blocker triage, fund-strategy review before remediation |
| `deterministic_merge` | Accepted verdicts converted by a merger script into cache/config/correction rows | GICS cache updates, scoped accepted residuals, low-risk enrichment |
| `config_patch` | Scoped JSON/config correction with evidence, mechanism, confidence, and audit trail | Per-CIK subtotal patterns, rate scale, identifier format, fund strategy override |
| `pipeline_patch` | Code/config/tests in an isolated branch or worktree | Parser changes, dedup logic, validation rule changes, source reconciliation fixes |

For pipeline patches, require:

- Targeted tests for the mechanism.
- False-positive or regression tests.
- Before/after metrics for the affected artifact.
- No unexplained validation regression.
- PR-style summary describing mechanism, evidence, changed files, commands run, and residual risk.
- Human merge decision.

This branch/worktree rule matters most for source blocker remediation. Directly editing generated CSVs, source reconciliation residuals, or frontend JSON can hide the error mechanism and make validation look better without making the pipeline correct.

## Validation And Merge Gates

Success criteria should differ by workflow type.

For enrichment workflows:

- Labels belong to the allowed vocabulary.
- Pilot accuracy/F1 exceeds threshold.
- Evidence quality exceeds threshold.
- No high-confidence invalid labels.
- Coverage and fair-value impact are reported.
- Deterministic merge is reproducible from verdicts.

For source blocker resolution:

- Targeted blocker groups are resolved or explicitly documented as residuals.
- Source reconciliation improves for the intended CIK-quarter.
- No new source-only or pipeline-only blockers appear elsewhere.
- GAV, pct-of-net-assets, count stability, and position purity checks do not regress without explanation.
- Mechanism evidence is documented.
- Residual risk is explicitly stated.

For validation-rule workflows:

- Agents cannot weaken thresholds as part of review.
- Validator false positives require evidence tied to source or independent artifacts.
- Rule changes require held-out validation and regression checks.
- Passing fewer rows is not itself success; the rule must become more correct.

For pipeline patches:

- The patch must be made in an isolated branch or worktree.
- Tests and validation commands in the manifest must pass.
- Validation deltas must be attached to the patch report.
- A human must decide whether to merge.

## Proposed Repository Layout

Target layout:

```text
docs/agentic_review_workflow_engine/README.md

schemas/agent_review/
  workflow_manifest.schema.json
  evidence_bundle.schema.json
  verdict.schema.json
  pilot_score.schema.json

scripts/agent_review/
  build_worklist.py
  build_bundles.py
  run_pilot.py
  validate_verdicts.py
  score_pilot.py
  merge_verdicts.py
  summarize.py
  prepare_patch_branch.py
  validate_patch.py

data/output/agent_review/{workflow_id}/
  manifest.json
  worklist.csv
  calibration/
  bundles/
  verdicts/
  scores/
  summaries/
  patch_reports/
```

This is a target design. The initial implementation can wrap existing assets rather than replacing them. For example, fund-strategy review already has grouped worklists, bundles, schema validation, and summaries. GICS already has worklists and merge scripts. FAIL verification already has a strong review-only contract. The engine should generalize these controls gradually.

## Migration Path From Existing Workflows

1. Keep this shared abstraction documented so future workflows use the same language for bundles, verdicts, calibration, mutation, and merge gates.
2. Add generic manifest and schema files under `schemas/agent_review/`.
3. Port fund-strategy review first because `pipeline/fund_strategy_group_review.py` already builds bundles and validates verdicts.
4. Wrap GICS as a workflow while preserving its current cache and aggregate-header integration initially.
5. Build source-blocker review next using source reconciliation residual artifacts and the packet logic in `pipeline/bdc_cik_validator.py`.
6. Add FAIL verification using the no-mutation structure from `docs/constrained_fail_verification_plan.md`.
7. Add branch/worktree patch mode last, after verdict, score, and validation reporting are stable.

This order avoids using agents to mutate the most dangerous parts of the pipeline before the evidence and validation machinery is mature.

## Risks And Controls

| Risk | Control |
|---|---|
| Known-good calibration rows are easier than unresolved rows | Stratified calibration, held-out validation, and post-pilot unresolved sampling |
| Agents optimize for reducing flags instead of correctness | Score verdict accuracy and evidence quality, not just validation improvement |
| Direct artifact edits hide the error mechanism | Use deterministic merge or isolated patch branches; do not hand-edit generated CSV/JSON outputs |
| High label accuracy does not prove pipeline patch safety | Require tests, before/after metrics, and independent validation gates |
| Validation rules can be weakened to fake success | Separate review from validator changes; require held-out checks for rule edits |
| Global rules create cross-CIK regressions | Prefer per-CIK config first; require false-positive tests before global promotion |
| Evidence bundles omit decisive source context | Bundle schema, evidence IDs, artifact hashes, and pilot feedback |
| Agents overstate confidence on ambiguous cases | Track confident-wrong rate and abstention quality; require residual uncertainty in verdicts |
| Human review becomes ceremonial | Require merge summaries with mechanism, evidence, metrics, and residual risk |

The workflow should make escalation normal. A documented `INSUFFICIENT_EVIDENCE`, source conflict, or unresolved blocker is a valid outcome when the evidence does not support a safe correction.

## Design Boundary

This document describes a reusable framework, not a finished implementation. It should guide future scripts, schemas, and Codex skills, while keeping the strongest current project constraint intact: public data should not look more precise than the validation evidence supports.

The near-term practical step is to reuse existing code where it is already close to the target shape, especially fund-strategy bundles and FAIL-verification verdict contracts. The longer-term step is a single `agent_review` harness that can run calibrated, evidence-backed workflows across enrichment, validation review, blocker triage, deterministic correction merges, and isolated pipeline patches.
