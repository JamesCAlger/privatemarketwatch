# BDC CIK Validator Skill

## Purpose

Validate one BDC CIK across one or more CIK-quarters before drafting any
filer-scoped correction. The skill uses two independent axes:

- Row-level source reconciliation: are the right positions present and are the
  values tied to cached source facts?
- GAV/fund-level reconciliation: does aggregate exposure reconcile to an
  independent denominator for the same CIK-quarter?

GAV is a gate plus context. It is not a substitute for row-level source
reconciliation.

## Required Packet

Every CIK packet must include:

- `source_reconciliation`: source-only blockers, residual mechanisms, and
  evidence for missing, extra, or mismatched rows.
- `unified_holdings_summary`: current row count and fair value by
  CIK-quarter from `private_markets_holdings.csv`.
- `gav_reconciliation`: holdings-to-denominator rows for the same CIK-quarters,
  including denominator source, denominator scope, adjusted ratio, GAV evidence
  scope, and gate role.
- `position_quality_context`: pct-of-net-assets, aggregate leak, duplicate
  dimension, and comparative-period context.
- `validation_matrix`: combined source/GAV status by report date.

Build packet data from cached local artifacts only. Do not call SEC EDGAR or
third-party sites unless the user explicitly requests fresh downloads.

## GAV Gate Roles

- `strong_gate`: denominator is `investments_at_fair_value` and not flagged as
  non-indexable or ambiguous.
- `moderate_gate`: denominator is a clear scoped total-assets proxy, currently
  `total_assets_companyfacts`, and not non-indexable.
- `context_only`: denominator is missing, weak, ambiguous, N-PORT total-assets
  only, or explicitly non-indexable.

Weak or missing GAV can provide context but must not block a correction by
itself.

## Validation Matrix

- Source blockers plus GAV undercoverage usually indicates missing extraction,
  parser, or indexability work.
- Source blockers plus GAV ok can be legitimate non-indexable rows or a
  denominator mismatch, but needs mechanism evidence.
- Source ok plus GAV overcoverage usually indicates duplicate/subtotal leakage
  or a denominator scope issue.
- GAV missing or weak does not block solely on GAV; rely on source
  reconciliation and document the aggregate uncertainty.

## Draft Correction Contract

Every draft correction must state:

- Expected row-level source reconciliation effect.
- Expected GAV effect.
- Whether GAV is a strong gate, moderate gate, or context-only signal for the
  affected CIK-quarter.
- Residual risk if source reconciliation and GAV disagree.

Draft correction rules:

- Do not accept a correction just because GAV improves.
- Do not accept a correction if row-level source reconciliation worsens.
- If strong GAV evidence exists and the draft claims completeness, the adjusted
  GAV ratio must move into range or the remaining residual must be explained.
- If GAV and source reconciliation conflict, classify the conflict as
  `denominator_scope`, `non_indexable_holdings`,
  `duplicate_or_subtotal_leakage`, or `unresolved`.

Drafts must validate against
`schemas/bdc_cik_validator/draft_correction.schema.json`.
