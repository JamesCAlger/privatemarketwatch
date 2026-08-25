# Agent Family Architecture -- Classifier and Fixer Lanes (design intent)

Status: DESIGN INTENT, not a project (owner decision 2026-08-22). This
document exists so that every new agent lane is built with convergence in
mind; the family layer itself is EXTRACTED from working lanes later, never
built upfront. See "Sequencing doctrine" below for why, and
`docs/provenance_columns_scoping.md` section 8 for the first lanes this
applies to.

## The two families

Every agent lane in this repo is one of two kinds, and the split tracks the
invariants that actually matter operationally -- grants, output shape, gate
style, cost profile, failure mode:

| | Classifier agents | Fixing agents |
|---|---|---|
| Grants | read-only | write (corrections dir, or code worktree) |
| Output | verdict leaf: bounded enum + evidence + confidence | artifact that changes data or code |
| Gate | gate-side re-derivation, gold-set calibration, panels | deterministic verifier per artifact type (source-anchor refusal matrix, B3 gate, predicted-delta rebuild) |
| Failure mode | misrouting (bounded by downstream gates) | silent corruption (hence heavier gates) |
| Escalation | "cannot classify" verdict | escalation leaf instead of the artifact |

The fixer family has two sub-species that share philosophy but little
machinery:

- **fixer/data** -- authors leaves (corrections, re-anchors); gated by
  schema validators + deterministic verifiers; the natural siblings.
- **fixer/code** -- authors a diff + regression test in an isolated
  worktree; gated by pytest + predicted-delta-only rebuild + operator
  merge. Inherits the escalation contract and dispatch plumbing from the
  family; does NOT inherit the leaf-validation harness. Do not force-share.

De facto members today: classifiers = B1 flag adjudicator, the anchor
adjudicator (`anchor_leaf.py`), the convention adjudicator
(`convention_leaf.py`), `agent_b2_diagnose`,
**`ledger-error-classifier` (BUILT 2026-08-25, not yet dispatched)**;
fixers/data = the B2 remediation workers. Still planned: fixer/data =
`anchor-leaf-author`; fixer/code = `parser-patch-author` (recommended
names; alternatives in scoping report 8.4). The
`verdict_leaf.py` / `correction_leaf.py` schema split is the family
boundary already expressed in code -- it was extracted from working lanes,
not designed upfront, and that is the model to repeat.

### ledger-error-classifier (classifier family)

Status: **BUILT, not dispatched** (batch `lec_smoke_20260825` prepared 2026-08-25;
dispatch requires admin shell per manifest `dispatch_requires=admin_shell`).

| Property | Value |
|---|---|
| Output | Verdict leaf (`pipeline/ledger_error_verdict.py`), enum: extraction_wrong / parser_drift / filer_error / amended / false_flag / ambiguous |
| Grant profile | `read_only_classifier` -- four read dirs: review_bundles, provenance_ledger.csv, private_markets_holdings.parquet, bdc_xbrl |
| Gate | `rederive_citations`: every `culprit_citations` entry re-derived from `provenance_ledger.csv` at intake; fabricated or unknown citations refused |
| Dispatch unit | One prompt per queue `review_id` (CIK x quarter x reason_code packet); dedup handled upstream by review_queue feed |
| Escalation | `{review_id}.escalation.json` sibling -- counts as coverage in `validate_dir`; gate does not gate escalation content |
| Drift fingerprint | `parser_drift` verdicts carry `drift_fingerprint.{field, transform_code, affected_row_ids}` -- the future `parser-patch-author` packet key |
| Convergence checklist | All 7 items satisfied (see changelog 2026-08-25 entry) |

## Three layers

1. **Universal harness** (already shared by everything): dispatcher +
   WorkerHome lifecycle, admin-shell dispatch, packet manifests + prompt
   building, intake validation (BOM strip, escalation siblings), trace
   harvest, cohort guard at the dispatch chokepoint.
2. **Family contract** (the layer this document defines the intent for):
   classifier = verdict-leaf schema conventions + read-only grant profile +
   calibration/panel harness + evidence-staging patterns; fixer = artifact
   contract + write grant profile + deterministic gate + re-grounding
   mandate ("filing shows X, extracted shows Y") + worked-example embedding
   + escalation leaf.
3. **Per-lane binding**: the specific enum/template schema, prompt, verifier,
   and dispatch-unit definition.

An improvement made at the family layer (e.g. a better context-management
technique for one classifier) ports to every lane in the family. That is
the point of the taxonomy.

## Rules that keep the taxonomy safe

- **Membership follows output + gate, NOT context depth.**
  `agent_b2_diagnose` is the instructive edge case: classifier-shaped
  output (mechanism verdict), fixer-grade context (filing + extracted
  re-grounding). It is a classifier. Context profile is a per-lane dial,
  not a family invariant -- techniques port, staging budgets are
  recalibrated per lane.
- **Grants NEVER port through the family layer.** A classifier must not
  gain write access by inheriting fixer scaffolding. Grant profiles are
  per-lane, reviewed per-lane.
- **Evidence visibility never ports either.** No classifier may see the
  outputs of a fixer whose work it might later gate. Independence of the
  validation layer is per-lane and non-negotiable; family sharing is for
  scaffolding (prompt patterns, evidence primitives, leaf schemas,
  harvest/eval tooling) only.
- **Verdicts must be re-derivable.** Any classifier verdict that routes
  work must be checkable gate-side from the evidence it cites, by machinery
  the classifier does not control (same principle as `apply_packet`
  re-verifying source anchors gate-side).

## Sequencing doctrine: extract, don't pre-build

The family layer is formalized only when there are working instances on
both sides of a contract to generalize from -- concretely, when the second
NEW lane in a family is running. Until then, new lanes are built ad hoc on
the existing universal harness, exactly as every successful lane so far was
built (canary first, gates before fleets).

Why: designing family contracts from n=2 data points that are about to
change shape is the AGENTS.md anti-pattern (refactoring before target
behavior is pinned preserves guesses behind cleaner abstractions), and a
standalone "agent framework" project is track-1 work queued in front of
track-2 data-quality work. The porting benefit is mostly captured for free
by building each lane against the convergence checklist below.

**The one shared asset worth building early** (it has three consumers
today, it is not an abstraction): the shared cached-filing search primitive
needed by gold-set, review, and adjudication agents alike (see
full-filing-search adjudication notes).

## Convergence checklist for any new lane

Build every new lane so the later extraction is trivial:

1. Output is either a verdict leaf or a gated artifact -- never both,
   never free text.
2. Escalation is a first-class sibling artifact (`*.escalation.json`
   convention), never a degraded low-confidence output.
3. The gate is deterministic and lives outside the agent's write reach.
4. Grant profile documented per-lane at dispatch (read set, write set,
   execution rights).
5. Evidence citations sufficient for gate-side re-derivation of the
   verdict/artifact.
6. Prompt scaffolding (re-grounding, worked example, CLI call-operator
   lines) taken from the nearest family sibling, divergences documented.
7. Dispatch unit + dedup-against-existing-queues defined before the first
   canary.

## Naming convention (owner decision 2026-08-22)

Agent lane names are `<target>-<family suffix>`, kebab-case, never letter
codes (B1/B2 are overloaded -- they also name position-matching tiers --
and letter codes hide the grant profile):

- **`...-classifier`** -- classifier family. Output is a verdict leaf;
  grants are read-only. Example: `ledger-error-classifier`.
- **`...-author`** -- fixer family. Output is a gated artifact; grants
  include a write target. The middle of the name says WHAT is authored:
  `...-leaf-author` for fixer/data lanes (correction leaves, anchor
  leaves), `...-patch-author` for fixer/code lanes (diff + regression
  test). Examples: `correction-leaf-author`, `anchor-leaf-author`,
  `parser-patch-author`.

The suffix encodes the family (and therefore the grant/gate shape); the
prefix encodes the target. Reading a lane name should tell you what it
writes and how it is gated without looking anything up.

Deterministic MODULES never take either suffix (e.g. `provenance_triage`),
so a suffixed name always means an agent lane and a bare name always means
code. Legacy lane names (B1, agent_b2 tooling paths) are grandfathered --
the convention applies to new lanes; renaming the B2 scripts/dirs is
cosmetic churn with no benefit.
