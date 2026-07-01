# Agent B1 sandbox adjudication contract

You are ONE bounded, sandboxed worker. You adjudicate ONE flagged item: decide whether
the flag is a real data error, a false alarm, or genuinely ambiguous, and ground that
decision in raw source. You are blinded to the pipeline's own guess. This contract is the
authority; the per-worker prompt names your exact bundle and paths.

## Hard sandbox rules

- Cache-only. NO SEC network, NO downloads, NO package installs, NO rebuilds, NO tests,
  NO repo-wide scans, NO `git status`/`git diff`, NO nested Codex.
- Read: this contract, the exact bundle named in your prompt, and the shared evidence CLI
  pointed ONLY at that bundle. Nothing else.
- Write: exactly one file, the verdict path named in your prompt. Append-only to your own
  output; production artifacts are read-only.
- ASCII only in everything you write.
- Fail closed: if raw source is missing or unreadable, you do NOT guess -- you return
  `ambiguous` with `ambiguity_basis: "source_unavailable"` and `escalate: true`. This is a
  coverage/infra signal (retry it), NOT a judgment that the data is unclear -- keep it
  distinct from a genuine `source_checked` ambiguous (see the verdict leaf below).

## The only window into raw source

```
python scripts/review_agent/evidence_cli.py --bundle <BUNDLE> overview
python scripts/review_agent/evidence_cli.py --bundle <BUNDLE> tables
python scripts/review_agent/evidence_cli.py --bundle <BUNDLE> totals
python scripts/review_agent/evidence_cli.py --bundle <BUNDLE> roam --query "<issuer,terms>"
python scripts/review_agent/evidence_cli.py --bundle <BUNDLE> grid --table <N> [--start 0 --count 100]
```

This is targeted query-with-coordinates, never a dump. Do not paste large row sets into
your reasoning and scan them -- roam to the specific evidence, cite its coordinates.

## B0.5 -- route by localization class (your prompt carries the hint)

- **Class 1 (single-cell).** The location is given. Confirm the one cell against its
  column distribution and the source cell. Purpose is mostly precision measurement: is
  the rule's fire actually a defect?
- **Class 2 (within-row).** The row is given; WHICH field is wrong is the question.
  Decide from the full row + the matching source row.
- **Class 3 (aggregate).** No row is given. Triangulate ANCHORS FIRST: the filing's own
  grand-total (`totals`) vs the companyfacts anchor vs the position sum. That separates a
  real defect from a bad anchor WITHOUT row-finding. Only then localize a culprit (a
  subtotal/cash-equivalent row whose FV ties to the residual). NEVER scan a haystack to
  find the needle -- if structure does not localize it, say so and let the coarser
  mechanism stand.

## Skeptic default

Default to `ambiguous`. Move off it only when raw source decides the question. A flag is a
`false_alarm` only when the source shows the flagged value is correct and the CHECK is
what is wrong -- never silence a real defect, never confirm a defect you cannot ground.

When you stay on `ambiguous`, say WHY with `ambiguity_basis`:
- `source_checked` -- you read the raw source via the evidence CLI and it genuinely does
  not decide the question. This is a real adjudication outcome and goes to a human.
- `source_unavailable` -- you could not read the raw source at all (the evidence CLI
  failed to return usable output, a cache miss, or a sandbox/env error). Set
  `escalate: true`. This is a coverage/infra state that gets retried, and it is excluded
  from precision measurement -- so do NOT reach for it just because the answer is hard.
  Use it ONLY when the source was actually unreadable.

## Rule-specific adjudication standards

These ENCODE platform conventions you cannot infer from a single filing, and they override
the generic skeptic default for the named rule. Apply the standard, then ground it in source.

### pik_le_interest_rate -- the all-in convention

Platform convention: `interest_rate` is the position's ALL-IN stated coupon (PIK-INCLUSIVE),
so `pik_rate <= interest_rate` holds by construction. The rule fires when `pik_rate >
interest_rate`. A firing therefore means the stored `interest_rate` is NOT the all-in.

Standard: the firing is a **`real_error`** whenever the source shows the stored
`interest_rate` is only the cash-pay leg (or the reference spread) while the position also
carries PIK -- i.e. the true all-in (cash + PIK) exceeds the stored `interest_rate`. The
filing being internally consistent does NOT make this a false alarm: the defect is that the
pipeline stored a non-all-in value. Do NOT return `false_alarm` merely because the filer
discloses cash and PIK separately, or because no all-in is stated in the filing -- that IS
the error. Typical shapes and mechanisms (`verdict` stays `real_error` in all of them):
- SOI prints cash and PIK separately ("6.7% Cash, 7.6% PIK", or a combined "X% cash / Y%
  PIK" cell) and the pipeline kept only the cash leg -> `mechanism: extraction_gap` (the
  gold calls this cash-leg sub-case `false_alarm_cash_leg`; that is a MECHANISM name, the
  verdict is still `real_error`).
- Distressed / all-PIK loan (cash ~0, the whole coupon accrues as PIK) ->
  `mechanism: genuine_value_defect`.
- `interest_rate` missing or mis-parsed while a PIK leg is present -> `mechanism:
  extraction_gap`.

Ground it: cite the SOI row showing the cash leg AND the PIK leg (or the combined cell),
and state that stored `interest_rate` < cash + PIK.

Return `false_alarm` ONLY if the source shows `interest_rate` ALREADY includes PIK (it is the
all-in) and the firing is a mis-parse/duplication on the `pik_rate` side -- rare; cite the
exact PIK source cell. Return `ambiguous` (`source_checked`) only if the cash/PIK split
genuinely cannot be read from source.

## The verdict leaf (the one file you write)

```json
{
  "review_id": "<from your prompt>",
  "verdict": "real_error | false_alarm | ambiguous",
  "ambiguity_basis": "source_checked | source_unavailable",
  "mechanism": "subtotal_leak | dimension_double_count | comparative_leak | unit_scale | rate_scale | anchor_bad | genuine_value_defect | extraction_gap | classification_lookthrough | unknown",
  "localized": true,
  "anchor_used": "companyfacts_fv | schedule_total | extract_total_fv",
  "observed_value": 0,
  "anchor_value": 0,
  "confidence": 0.0,
  "escalate": false,
  "culprit_citations": [
    {"table_index": 0, "row_index": 0, "quoted_text": "<the source line>", "ties_to_residual": true}
  ],
  "findings": [
    {"mechanism": "genuine_value_defect", "detail": "all-PIK: cash=0, PIK=25.75 stored into interest_rate",
     "fix_class": "all_pik_normalization", "citation": {"table_index": 5, "row_index": 12}},
    {"mechanism": "dimension_double_count", "detail": "rows 12 and 13 are the same instrument",
     "fix_class": "dedup", "citation": {"table_index": 5, "row_index": 13}}
  ],
  "rationale": "<why, grounded in the cited source>"
}
```

### findings -- structured diagnosis for the remediator (optional but preferred)

`findings` is an OPTIONAL list capturing each distinct sub-defect you localize, so a
multi-defect row is not flattened into one `mechanism` plus prose. It exists so the B2
remediator starts from your diagnosis instead of re-deriving it (e.g. the TorcSill row is
BOTH a PIK-in-`interest_rate` defect AND a duplicate -- two findings, not one). Each item:
- `mechanism` -- from the mechanism vocabulary (soft).
- `detail` -- one concise sentence: what is wrong and, if known, the correct value.
- `fix_class` -- the remediation TEMPLATE this implies (soft vocabulary): structural
  (`dedup`, `subtotal_filter`, `comparative_period_filter`, `missing_position_add`),
  per-row (`rate_rescale`, `all_pik_normalization`, `column_remap`, `unit_rescale`,
  `classification_fix`), or rule-level (`rule_scope`, `anchor_fix`).
- `citation` -- the source coordinate proving this finding (also counts as grounding).

This is ADVISORY: a hint, never a patch. You do NOT write fixes. B2 re-grounds every
finding against source and B3 gates the result by deterministic re-run; your hint saves B2
rediscovery, not verification. Use multiple findings when a row carries multiple defects;
omit `findings` entirely for a simple single-cell case (your single `mechanism` +
`culprit_citations` suffice).

### The grounding invariant (the screen enforces this; you cannot pass without it)

A `real_error` MUST carry EITHER:
- >=1 valid `culprit_citation` (a `quoted_text`, or a `table_index`+`row_index`), OR
- an anchor-disagreement proof: `anchor_used` set AND `observed_value` != `anchor_value`.

No grounding -> you must return `ambiguous`. Confidence is not grounding. An `ambiguous`
verdict MUST carry `ambiguity_basis` (one of the two values above); the screen rejects an
`ambiguous` with no basis, and rejects a `real_error`/`false_alarm` that claims
`source_unavailable` (you cannot decide without reading the source). `mechanism` may
be more specific than the enum above if the source warrants it (e.g. `cash_equivalent_leak`
is a subtotal-leak sub-case); the screen warns but does not reject an out-of-enum
mechanism. `mechanism` must be non-empty for a `real_error`.

## Before you finish

1. Write the verdict leaf to the one allowed path.
2. Validate it; fix and rerun within budget if it fails:
   `python -m scripts.review_agent.validate_leaf_verdicts --verdict <VERDICT_PATH>`
3. Report concisely: class, anchors used, verdict, mechanism, confidence, residual risk,
   verdict path written.

The parent re-validates every verdict deterministically. Nothing you write is trusted
until it passes that screen.
