# Convention Adjudicator -- spec (rev 1, 2026-07-12)

Establishes ONE fact per filer: whether the filer's stated position-level
`interest_rate` is the ALL-IN coupon (PIK included) or the CASH leg only
(PIK on top). This is the agent lane for the residual that
`pipeline/rate_convention.py` cannot decide deterministically, and the
prerequisite for (a) normalizing `interest_rate` to all-in per the 2026-07-12
contract decision and (b) re-adding the retired `pik_le_interest_rate`
identity rule.

It is an ANCHOR-SHAPED agent, not a B1-shaped one: it adjudicates a per-CIK
metadata fact whose output is a promoted override, guarded by a deterministic
verify step the worker cannot game. It reuses the B1/anchor plumbing
wholesale: prompt/manifest/leaf lifecycle, `evidence_cli` filing access, the
Codex sandbox dispatch harness and all its known gotchas.

## 1. Scope and non-goals

- IN: one verdict per (cik, identifier-format-era): `all_in | cash_leg |
  indeterminate`, with quoted filing evidence, promoted to
  `data/overrides/rate_convention/<cik>.json`.
- OUT: modifying holdings (that is the migration's job), authoring rules
  (B2's job), anything in the fv_conservation chain, and any change to the
  deterministic classifier itself.
- `indeterminate` is a legal, promotable verdict. Filers whose filings do not
  disclose the convention get the conservative migration default (no PIK
  adjustment) plus a quality flag. Do not force a verdict.

## 2. Position in the system

NOT part of B1 -> B2 -> anchor -> B2. A standing, event-driven metadata lane:

```
rebuild -> pipeline.rate_convention (deterministic)  -> rate_convention.csv
             |                                            ^
             | unknown / conflict bases                   | override merge
             v                                            | (Section 8)
        run_convention discover -> prep -> [codex worker] -> verify -> promote
                                                              |
                                             data/overrides/rate_convention/<cik>.json
```

- **Trigger**: `convention == unknown` in the latest `rate_convention.csv`
  (all bases: no_signal, s1_unstable, *_conflict), OR a previously promoted
  override demoted by the freshness check (Section 8).
- **Run-once termination**: discover skips any CIK with an existing override
  whose `format_era` still matches (same pattern as anchor's
  `ANCHOR_OVERRIDES / cik / quarter.json` existence check).
- **Hard ordering constraint**: a filer must have a promoted verdict (or the
  documented indeterminate default) BEFORE the all-in normalization migration
  touches it.
- **Cadence**: idle in steady state. Re-runs only when a new PIK-active filer
  lands in unknown or a label is demoted.
- **Fleet rules unchanged**: operator dispatch from an admin terminal, ONE
  Codex fleet per machine, MaxParallel <= 2, retry as a NEW batch id.

## 3. Module layout (mirrors agent_anchor)

| Piece | Path |
|---|---|
| Driver (discover/prep/verify/promote) | `scripts/agent_convention/run_convention.py` |
| Leaf schema + validation (pure) | `pipeline/convention_leaf.py` |
| Verify cross-checks (pure) | `pipeline/convention_validation.py` |
| Batch scratch | `data/output/agent_convention/<cik>/...`, `data/output/agent_convention/batch/<batch_id>/` |
| Override store (production consumer input) | `data/overrides/rate_convention/<cik>.json` |
| Dispatcher | `scripts/dispatch_convention_workers.ps1` (thin clone of `dispatch_agent_b_workers.ps1`) |

## 4. discover

`python -m scripts.agent_convention.run_convention discover <batch_id>
[--rate-convention data/output/rate_convention.csv] [--cohort-only] [--top-n N]`

- Targets: rows with `convention == unknown` (optionally cohort-scoped via
  `WRAPPER_COHORT_MANIFEST_FILE`), minus CIKs with a current-era override.
- Priority: descending latest-quarter PIK fair value (join done in discover;
  the classifier CSV carries no FV). `--top-n` bounds the batch.
- Target filing: the CIK's LATEST quarter with PIK evidence that has a cached
  filing. Convention is a filer/format-era property; one well-chosen filing
  answers it. Record `target_quarter` + accession in the worklist.
- Writes `batch/<batch_id>/convention_worklist.csv`:
  `cik, target_quarter, basis (why unknown), n_pik_rows, pik_fv, sample_positions`.
- Bundle guarantee: reuse the existing review-bundle generator (the
  `prepare_fresh_batch` seam) for any target CIK-quarter without a bundle --
  `evidence_cli` opens filings through bundles, and its roam covers the whole
  filing once one document resolves.

## 5. prep -- prompt and manifest

`run_convention prep --cik <cik> --target-quarter <q>` writes
`prompt.<q>.md` + `manifest.<q>.json` (anchor pattern), leaf destination
`data/output/agent_convention/<cik>/leaf/convention.<q>.json`.

**Blindness rule (deliberate divergence from the anchor prompt, which passes
companyfacts numbers in): the prompt contains NO classifier signals** -- no
violation counts, no ceiling/nearcap stats, no income ratios, no phrasing
counts. Passing the numeric prior in would anchor the worker toward the
answer the deterministic layer already suspects, and Section 6's cross-check
would then be partially circular. The worker determines the convention from
the filing alone; the numbers meet its verdict only at verify time.

The prompt DOES contain (navigation only, convention-neutral):
- the target cik/quarter/accession and 3-6 SAMPLE PIK POSITION issuer names
  (from rows with `pik_rate > 0`) so the worker can find the right SOI rows;
- the three disclosure patterns to look for: (i) rate column is total with
  "(incl. x% PIK)" -> all_in; (ii) separate Cash / PIK columns or
  "x% cash, y% PIK" text -> cash_leg; (iii) "+ x% PIK" appended after a
  spread-form rate -> cash_leg (additive quote); plus column-header and
  footnote text as first-class evidence;
- tool lines (read-only, this cik only), same as anchor:
  `evidence_cli --bundle <bundle.json> totals|grid|roam|tables` and
  `data_query_cli --cik <cik> query --sql ...` (data_query is for LOCATING
  positions, not for deciding);
- the instruction that `indeterminate` with a documented search trail is a
  valid answer, and the leaf format (Section 6). ASCII only.

## 6. Leaf schema (`pipeline/convention_leaf.py`)

One JSON object; REQUIRED = (`cik`, `target_quarter`, `convention`,
`citations`, `rationale`, `confidence`).

```json
{"cik": "1812554", "target_quarter": "2025-12-31",
 "convention": "all_in",                      // all_in | cash_leg | indeterminate
 "column_semantics": "single 'Interest Rate' column; PIK shown parenthetically",
 "citations": [
   {"kind": "header",   "quote": "Interest Rate (2)", "where": "SOI p.12"},
   {"kind": "footnote", "quote": "(2) Includes paid-in-kind interest of ...", "where": "SOI notes"},
   {"kind": "position", "issuer": "Acme Corp", "quote": "12.50% (incl. 3.00% PIK)",
    "printed_total": 12.50, "printed_pik": 3.00}],
 "applies_from": "2022-03-31", "applies_note": "same column layout across sampled filings",
 "rationale": "...", "confidence": 0.9}
```

Validation (pure, mirrors `anchor_leaf.validate_anchor_leaf`):
- `convention` in the allowed set; confidence in [0, 1]; ASCII.
- A decided verdict REQUIRES >= 1 header/footnote citation AND >= 2 position
  citations with parsed `printed_*` numbers. `indeterminate` instead requires
  a `search_trail` list (what was checked and found silent).
- Position citations must name issuers that exist in the filer's holdings
  (checked at verify, not here -- keeps the leaf module IO-free).

## 7. verify -- the un-gameable step (`pipeline/convention_validation.py`)

Schema check, then three deterministic cross-checks the worker cannot
influence (analogue of the anchor's balance-sheet closure):

1. **Citation reconciliation** (per cited position): find the issuer's row in
   unified holdings for that quarter and test the claimed mapping --
   `all_in` requires stored `interest_rate ~= printed_total` and
   `pik_rate ~= printed_pik`; `cash_leg` requires stored
   `interest_rate ~= printed_total - printed_pik` (or the printed cash
   figure). A citation that reconciles under the OPPOSITE convention is a
   hard fail. Tolerance 0.05pp; >= 2 of the cited positions must reconcile.
2. **Signal contradiction gate**: verdict `cash_leg` on a filer with the
   statistical-ceiling signature (0 violations, `n_dual >= 60`,
   `n_nearcap >= 8`), or verdict `all_in` on a filer with S1-convicting
   violations, -> `refused_contradiction`. The verdict is not promoted; the
   CIK is flagged for human review (both sides documented). The worker never
   saw these numbers (Section 5), so agreement is evidence, not echo.
3. **Tier capping** (anchor precedent for single-source evidence): verdict
   resting on ONE filing with no header/footnote citation (positions only)
   is capped at MEDIUM regardless of stated confidence; `applies_from`
   earlier than the sampled filings is capped at MEDIUM.

`verify` exit 0 only if schema ok + reconciliation ok + no contradiction.

## 8. promote and consumption

- `promote` copies the verified leaf to
  `data/overrides/rate_convention/<cik>.json` with provenance
  (`batch_id`, verify tier, reconciled citation count). REFUSES unless
  verify ok -- same contract as anchor promote.
- `pipeline/rate_convention.py` gains an override merge (same utf-8-sig
  discipline as all worker-written JSON):
  - override supersedes a deterministic `unknown`;
  - override NEVER silently overrides a deterministic conviction: if a later
    rebuild's signals contradict a promoted override (new violations under an
    `all_in` override; ceiling signature under `cash_leg`), the merged label
    demotes to `unknown/demoted_override` and the CIK re-enters discover.
    This is the freshness check -- stale verdicts self-detect, like every
    other signal in the classifier;
  - `indeterminate` overrides surface as `indeterminate` (distinct from
    `unknown`): the migration applies the conservative default (no PIK
    adjustment) and the quality flag, and discover stops re-queueing the CIK.
- The all-in migration consumes ONLY the merged table. It normalizes
  `cash_leg` filers, leaves `all_in` filers unchanged, and refuses to touch
  `unknown` (as opposed to `indeterminate`) filers.

## 9. Dispatch runbook (operator, admin terminal)

```
python -m scripts.agent_convention.run_convention discover conv1 --cohort-only --top-n 21
# per worklist row (or via the thin dispatcher):
python -m scripts.agent_convention.run_convention prep --cik <cik> --target-quarter <q>
powershell -File scripts\dispatch_convention_workers.ps1 -BatchId conv1 -MaxParallel 2 -TimeoutMinutes 30
python -m scripts.ensemble.strip_verdict_bom   # workers write BOMs; strict utf-8 readers crash
python -m scripts.agent_convention.run_convention verify  --cik <cik> --target-quarter <q>
python -m scripts.agent_convention.run_convention promote --cik <cik> --target-quarter <q>
python -m pipeline.rate_convention             # rebuild merged table; confirm unknowns dropped
```

All Codex sandbox gotchas apply verbatim: one fleet per machine, MaxParallel
<= 2 (shared sandbox-account password reset races), stale setup markers ->
always retry as a NEW batch id (`prep_retry` pattern), kill in-flight workers
only from an elevated shell, per-run CODEX_HOME cleanup (disk-bloat fix).

## 10. Batch sizing and expected outcomes

- First batch: the 21 cohort unknowns (or `--top-n 6` by PIK FV: Blue Owl x2,
  Ares SIF, Carlyle, Diameter, Monroe -- ~$7.5bn of the $9.0bn unknown FV).
- Expected verdict mix, from the residual's shapes: Blue Owl x2 (no dual-rate
  rows) and Ares SIF (no near-cap mass) should decide cleanly from column
  semantics; Monroe/Stellus (s1_unstable) may split by format era -- the leaf
  `applies_from` field exists for exactly this; a small tail may land
  `indeterminate`.
- Definition of done for the migration precondition: every cohort filer is
  `all_in`, `cash_leg`, or `indeterminate` in the MERGED table -- zero
  `unknown` remaining.

## 11. Tests (before first dispatch)

- `tests/test_convention_leaf.py`: schema acceptance/rejection incl. the
  decided-vs-indeterminate citation requirements.
- `tests/test_convention_validation.py`: citation reconciliation under both
  conventions (incl. the opposite-convention hard fail), contradiction gate
  both directions, tier capping.
- `tests/test_rate_convention.py` additions: override merge precedence,
  demotion on later contradiction, indeterminate passthrough.
- Driver `discover` run-once test (existing override -> skipped).

## 12. Open decisions (operator)

1. Format-era keying: v1 keys overrides by CIK with `applies_from`; a filer
   with a mid-history convention change needs two eras -- acceptable to defer
   until Monroe/Stellus verdicts show whether it is real.
2. Whether `indeterminate` cohort filers ship in the v1 migration with the
   conservative default, or hold the migration until adjudicated -- decide on
   the observed count (expected: <= 3 filers, immaterial PIK FV).
