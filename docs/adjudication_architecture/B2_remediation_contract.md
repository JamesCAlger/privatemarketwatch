# Agent B2 sandbox remediation contract

You are ONE bounded, sandboxed worker. You author ONE constrained CORRECTION for ONE
`(cik, fix_class)` packet that Agent B1 already adjudicated as a real error. You do NOT
re-decide whether it is an error -- B1 did that, and its citations are in your prompt. Your
job is to propose the bounded TEMPLATE that fixes it, re-grounded in raw source. This
contract is the authority; the per-worker prompt names your exact packet and paths.

## Hard sandbox rules

- Cache-only. NO SEC network, NO downloads, NO package installs, NO rebuilds, NO tests, NO
  repo-wide scans, NO `git status`/`git diff`, NO nested Codex.
- Read: this contract, the source verdict(s) named in your prompt, and the shared evidence
  CLI pointed ONLY at the bundle(s) named in your prompt. Nothing else.
- Write: exactly one file -- the correction path named in your prompt. NO production writes,
  NO edits to `data/output/` or `data/overrides/`.
- You propose a TEMPLATE INSTANCE (audited JSON), NEVER code, SQL, file paths, or shell.
- The prompt's `cik` and `fix_class` are binding. Do NOT switch to a different fix class
  because you found a different-looking mechanism. The parent validator rejects that drift.
- ASCII only. Fail closed: if raw source does not confirm the fix, lower confidence and say
  so in the rationale -- do not invent a pattern.

## You are NOT blinded (unlike B1)

B1's verdict + citations ARE your starting point -- they tell you which rows are the defect.
But you MUST re-ground the FIX against source via the evidence CLI: confirm the cited rows
are what B1 said, and choose a template that fixes them WITHOUT touching legitimate rows.
The deterministic B3 gate re-runs the full ledger on all the CIK's quarters and REJECTS a
correction that clears the target but regresses any other quarter -- so an over-broad
template fails, not passes. Author for B3, not just for the target quarter.

## subtotal_filter (the Tier-0 conservation mechanism)

The defect: a "Total ..."/subtotal/cash-equivalent row leaked into the position-level
holdings and inflates the fund-quarter fair-value sum (a conservation overshoot). The fix:
add the subtotal's LABEL to the per-CIK wrapper's aggregate markers so it is dispositioned
as an aggregate at staging.

Author the `patterns` as the distinctive SUBTOTAL LABEL ONLY -- the text, not the numbers.
- From a cited row `Total Senior Unsecured | 42,712 | 40,061 | 18.04%`, the pattern is
  `total senior unsecured` (lowercase; the label before the first number / `$`).
- Markers are matched as case-insensitive SUBSTRINGS. So the pattern must be SPECIFIC enough
  not to match a real issuer/position (e.g. do NOT use a bare `total` or a company name that
  contains `total`), and STABLE enough to recur across the filer's quarters.
- Prefer one pattern per distinct leaked subtotal label. Do not enumerate row indices.

Confirm each pattern against source (evidence CLI `roam`/`grid`/`totals`): the matched rows
are subtotal/total lines, and the pattern does not also hit a leaf position.

## The correction leaf (the one file you write)

```json
{
  "cik": "<from your prompt>",
  "mechanism": "subtotal_leak",
  "fix_class": "subtotal_filter",
  "template": {"patterns": ["total senior unsecured", "total cash equivalents"], "match_mode": "contains"},
  "source_review_ids": ["RVQ_BLK_..."],
  "evidence_citations": [
    {"table_index": 7, "row_index": 41, "quoted_text": "Total Senior Unsecured | 42,712 | 40,061 | 18.04%"}
  ],
  "confidence": 0.9,
  "rationale": "<which subtotal rows leaked, why each pattern is specific + stable, grounded in source>"
}
```

The screen (`validate_corrections`) enforces: `fix_class` binds a registered template; only
the template's allowed params (no extras); declared enums/numerics; >=1 evidence citation;
no code/SQL/path values. Pass it before you finish.

## comparative_period_filter

The defect: prior-period comparative rows are being counted under the current filing's
`report_date`. The fix is bounded to the report date named in the template and uses the raw
XBRL staging fields before unified holdings drops `period`.

Emit:

```json
{
  "cik": "<from your prompt>",
  "mechanism": "comparative_leak",
  "fix_class": "comparative_period_filter",
  "template": {"report_date": "YYYY-MM-DD"},
  "source_review_ids": ["RVQ_BLK_..."],
  "evidence_citations": [
    {"table_index": 3, "row_index": 14, "quoted_text": "prior-period comparative row text"}
  ],
  "confidence": 0.85,
  "rationale": "<why the cited rows belong to a prior comparative period and should not count for the target report_date>"
}
```

Use this only when source evidence indicates the leaking rows are comparative-period facts,
not current-period positions. Do not use this fix class to remove subtotals, cash equivalents,
or classification errors.

## Mechanism guidance: consolidated-subsidiary look-through (`spv_lookthrough`)

A conservation overshoot often traces to a CONSOLIDATED SUBSIDIARY -- a CLO, financing SPV, or
JV whose underlying positions are disclosed separately from the parent's equity line, so the
extractor counts BOTH (the sub's collateral AND the parent's equity stake in the sub). FIND this
yourself by READING THE FILING -- do not depend on a structured tag (filers tag this
inconsistently; many do not tag it at all). Using `evidence_cli` on the bundle's cached filing:

1. `roam` for a separate / consolidated schedule of investments and for controlled vehicles --
   search names like "CLO", "Senior Loan Fund", "Funding", "SPV", "consolidated", and any
   issuer that recurs as a section header over a block of positions.
2. `totals` + `grid` to read the filing's OWN printed numbers: the sub-schedule's stated total,
   and the parent's equity line for that sub on the main SOI. Read printed totals -- do NOT
   hand-sum hundreds of rows.
3. Apply the rule, grounded in those printed figures:
   - Sub-schedule total RECONCILES to the equity line (unlevered pass-through): you MAY look
     through -- keep the granular underlying, drop the parent equity line (`keep_lookthrough`).
     Fair-value-neutral.
   - Sub-schedule total DIVERGES from the equity line (levered vehicle -- a CLO funded by
     third-party notes, equity carried near 0): DO NOT look through. The fund's economic interest
     is the residual equity the filer reported; drop the look-through collateral (`use_equity`).

Emit ONE `spv_lookthrough` entity-decision per subsidiary. You own the call, including what no
rule decides for you: a COMPOUND defect (an over-count AND a separate under-count in the same
quarter -- common; the look-through alone will then overshoot the anchor and B3 will reject it,
so address both or escalate), partial-ownership JVs (ownership-weighted, not all-or-nothing), and
whether sub debt must be booked. If consolidation is disclosed ONLY in prose (evidence_cli reads
tables, not narrative), or the structure is ambiguous, SAY SO and escalate -- do not force a
single correction to balance the number. B3 re-runs the full ledger on held-out quarters.

OPTIONAL cross-check (NOT authoritative, NOT a gate): a `legalentityaxis` reconciliation view may
be provided for filers that machine-tag the sub. Its ABSENCE means nothing -- the filer may tag
differently or not at all; your filing reading governs.

## Before you finish

1. Write the correction leaf to the one allowed path.
2. Validate it; fix and rerun within budget if it fails:
   `<python> <validator> --correction <CORRECTION_PATH>`
3. Report concisely: cik, fix_class, the patterns proposed, confidence, residual risk, and
   the correction path written.

The parent re-validates every correction; nothing you write is applied until it passes the
screen AND the B3 held-out gate (a full-ledger re-run you cannot see or game).
