# Published-Basis Conservation Gate — Design

Date: 2026-09-07
Status: approved design (owner, "do it" on the revised Approach A), pending implementation plan
Scope gate: everything here ships BEFORE any agent fleet runs on Q2 2026 (2026-06-30).
Owner decisions captured: Approach A revised (one basis, one check, wired into acceptance);
public headline stays the straight sum (AGENTS.md contract untouched); subsidiary-flagged rows
are NOT removed from the headline or the gate numerator; four mechanics fixes ride along.

## Problem

Q1 2026 (2026-03-31) was signed off 7/7 under thresholds v2 with $4.09B of over-included
fair value in the cohort headline (1.07% of $381.9B). All of it is over-inclusion; one fund
under-extracts. Every dollar was measured by at least one check and none of the checks that
measured it feed the acceptance verdict.

| Fund | CIK | Excess FV | Mechanism |
|---|---|---|---|
| HPS Corporate Lending | 1838126 | $1.579B | JV look-through block on a bare axis (ULTRA III) |
| Goldman Sachs Private Credit Corp | 1920145 | $0.687B | cash equivalents counted as portfolio FV |
| Bain Capital Private Credit | 1899017 | $0.407B | 66 subsidiary-axis rows duplicating parent rows |
| TCW Direct Lending VII | 1715933 | $0.356B | same loans under two naming conventions |
| TCW Direct Lending | 1603480 | $0.323B | added cash row duplicating a native row |
| Silver Capital Holdings | 1674760 | $0.315B | added money-market row duplicating a native row |
| Fidelity Private Credit Fund | 1920453 | $0.196B | cash instrument on cash axis and null axis |
| GS Private Middle Market | 1772704 | $0.122B | documented inclusion (not a defect; listed for completeness) |
| four funds under $35M each | | $0.098B | mixed |

### Root causes (forensics 2026-09-07, all verified against artifacts)

1. **Two bases for one number.** The published headline is the straight sum of every cohort row.
   The conservation numerator (`scripts/shadow_conservation_engine.py::run_rule`,
   `pipeline/agent_rule.py::value_sum_by_quarter`, `pipeline/agent_b2_diagnose.py::_gate_rows`,
   `scripts/agent_b2/run_remediation.py::build_conservation_snapshots`) excludes `asset_category='CASH'`
   and `is_subsidiary=1` rows, with per-CIK carve-outs in `data/overrides/conservation_scope/`.
   The GAV check (`pipeline/validate_holdings.py`) uses `sum_holdings_fv_ex_sub` whenever a fund has
   subsidiary rows. The rows that inflate the headline are exactly the rows the checks drop, so
   nine of twelve defect funds reconcile to 0.000% while the headline is wrong. In Q1 the gap is
   $407M subsidiary (1 fund) + $1.29B cash (16 funds).
2. **The subsidiary exclusion is wrong in the other direction one quarter earlier.** Bain Q4 2025:
   parent rows $1,630.1M, subsidiary rows $54.1M (nine distinct first-lien loans), filer total
   $1,681.3M. Parent alone = 0.970, parent + subsidiary = 1.002. Q1 2026: parent $1,815.1M = anchor
   to the dollar, subsidiary rows $406.5M pure surplus. `is_subsidiary` is a dimension tag, not a
   duplication verdict; only the anchor test can decide it per quarter. The 2026-08-29 retain-and-flag
   decision calibrated on the duplicating case and silently hides the Q4 undershoot.
3. **Anchors were widened without saying so.** Anchor-lane overrides (`data/overrides/agent_anchor/`)
   replaced balance-sheet investment totals with grand totals that fold in cash equivalents
   (TCW VII $1,239M vs $657M; GS PCC $16,852M vs $16,509M; Silver Capital $447M vs $289M). Workers
   were told to reconcile UP to that figure and not delete, so adding rows was the only permitted
   move. The adds were authored against a frame where the cash rows were absent; the 2026-09-02
   cash-axis extraction fix then extracted them natively, and the duplicate-add guard
   (`_existing_position_keys`, keyed on exact identifier text) missed them because the rule text
   differs from the filing text. 56 added rows / $1.32B across 12 funds are on this footing.
   67 anchor leaves exist (59 for 2026-03-31); none declares what its grand total includes.
4. **Gating and promotion ran out of order.** HPS: batch gate verdict FAIL written 09:00:12; the
   worker's two rules (which reconcile to zero) written 11:12 and 11:18; nothing re-gated; rules never
   promoted. Silver Capital: gate PASS_NOOP 08:44 ("no rules authored"); a row_add promoted 10:49.
   `gate()` reads `corrected_holdings.<cik>.csv` from the last `apply()`, so a gate run after new rules
   but before a fresh apply evaluates a stale frame with no warning.
5. **Quarter-scoped exclusions expire silently.** 140 promoted rules across 82 CIKs; 35 scoped `all`;
   the rest carry hard date lists and cannot fire on a new quarter. The TCW VII dedup rule is scoped
   to 2025-09-30/2025-12-31 and its predicate still matches 27 Q1 rows worth $355.9M. No alert exists.
6. **The check that measures over-inclusion is muted.** `fv_conservation` fails map to `cons_superseded`
   in `scripts/shadow_validation_runner.py` (2026-06-16, "~80% false positive"), so they never reach
   the review queue. The acceptance contract still reads them from the ledger, but on the excluding
   basis, so Q1 passed `flagged_fv_share` at 9.855% against 10.0%.

## Decision

**Approach A (revised): one basis, one check, wired into acceptance.**

- The published row set is every row in `private_markets_holdings` for a cohort CIK-quarter. No
  exclusions. This is already the headline; it becomes the gate numerator too.
- The anchor is the filer's total for that same row set. Anchor overrides must declare their basis.
- Conservation stays at the 0.5% band; GAV tightens on strong anchors; acceptance gains an
  over-inclusion gate and an unfinished-investigation gate (thresholds v3).
- Subsidiary-heavy or cash-heavy funds that then fail are resolved per CIK per quarter through the
  existing Layer C exclusion mechanism with filing evidence. The gate forces the decision instead of
  making it silently.

Rejected: (B) keep two bases and publish the delta — two definitions of one number forever.
(C) headline follows the excluding gate — breaks the AGENTS.md all-classifications contract and does
nothing about added rows, which carry no cash tag. Original A (drop subsidiary rows from the headline)
— wrong for Bain Q4 and blind for the three non-cohort funds carrying $1.6B–$2.3B subsidiary blocks.

## Non-goals

- No change to the public headline, donuts, or the straight-`GROUP BY` reconciliation rule.
- No re-opening of the Q1 2026 sign-off or the Q4 2025 attestation. Re-running acceptance on Q1 under
  v3 is a verification step whose expected result is FAIL; that result is recorded, not remediated here.
- No new agent lanes, no changes to worker prompts beyond stating the anchor basis.
- No fix for the HPS ULTRA III JV block itself, the TCW VII naming duplication, or Bain's Q1
  subsidiary rows. Those are Q2-fleet work once the gates can see them.
- No SEC downloads. Everything rebuilds from cache.

## Design

### 1. One numerator

Definition, used verbatim in every implementation:

> `published_fv(cik, quarter)` = `SUM(fair_value)` over all rows of the unified holdings with that
> `cik` (10-digit padded) and `report_date`, with no category, dimension, or subsidiary filter.

Changes:

| Site | Today | After |
|---|---|---|
| `shadow_conservation_engine.run_rule` | `bdc_dimensions_raw IS NOT NULL AND <cash_filter> AND is_subsidiary<>1` | `cik IN wrapped` only (dims filter dropped; verified 0 cohort rows with NULL dims in Q1) |
| `agent_rule.value_sum_by_quarter` | drops CASH (with carve-outs) and `is_subsidiary=1` | straight sum per `report_date` |
| `agent_b2_diagnose._gate_rows` | mirrors above | mirrors above |
| `run_remediation.build_conservation_snapshots` | mirrors above | mirrors above |
| `validate_holdings` GAV numerator | `sum_holdings_fv_ex_sub` when `has_subsidiary_positions` | `sum_holdings_fv` always; `_ex_sub` column kept as informational |
| `agent_rule.CONSERVATION_EXCLUDED_CATEGORIES` | `{"CASH"}` | removed |
| `pipeline/conservation_scope.py` + `data/overrides/conservation_scope/*.json` | 5 carve-outs | module deleted; files archived under `data/overrides/_retired/conservation_scope/` with a README pointing here |

A single shared helper `pipeline/published_basis.py::published_fv_sql()` / `published_fv_frame()`
returns the SQL fragment and the pandas equivalent so the four numerator sites cannot drift again. A
test asserts the two agree on a fixture with cash, subsidiary, and added rows.

Consequence, stated up front: the 16 cohort funds holding CASH rows in Q1 ($1.29B) will flag unless
their anchor includes cash equivalents. That is the intended behaviour. Resolution is on the anchor
side (section 2), never by re-adding a numerator exclusion.

### 2. Anchor basis

**Schema.** `pipeline/anchor_leaf.py` adds a required key `basis` with two allowed values:

- `published_rows` — the total of everything the schedule of investments lists, including cash
  equivalents, short-term investments, and look-through / subsidiary-axis rows. Comparable to
  `published_fv` directly.
- `investments_ex_cash` — the balance-sheet investments line (what companyfacts
  `InvestmentOwnedAtFairValue` usually tags). Comparable to `published_fv` only when the fund has no
  cash-equivalent rows in holdings.

`validate_anchor_leaf` rejects a leaf without `basis`; `load_anchor_overrides` therefore ignores it and
the gate falls to the next anchor in priority (companyfacts, then schedule total). The anchor-lane
worker prompt and the `run_anchor` promote step require the field. The `components` list must be
consistent with the basis: a `published_rows` leaf whose grand total equals `companyfacts_fv` within
0.5% is rejected as mislabelled, and vice versa.

**Deterministic anchor candidates** (engine `RULES[fv_conservation].anchors`, in priority order):

1. `verified_override` with `basis=published_rows`.
2. `companyfacts_fv_plus_cash` — `investments_at_fair_value` plus a new `fund_financials` column
   `cash_equivalents_at_fair_value` extracted from the cached companyfacts JSON
   (`pipeline/extract_companyfacts.py::_BALANCE_SHEET_CONCEPTS`; candidates
   `CashEquivalentsAtCarryingValue`, `MoneyMarketFundsAtCarryingValue`, filer extensions matching
   `MoneyMarketFunds*AtFairValue`; cache-only, no download). Used only when the fund has CASH rows in
   holdings for that quarter AND the concept is tagged; otherwise skipped. New since the approved
   design; it removes most of the anchor-lane load that section 1 would otherwise create, and an
   overshoot against it is an honest flag (rows the extraction admitted but the filer did not tag as
   cash, or vice versa). The 16 Q1 cash funds are the calibration set: report how many resolve here.
3. `companyfacts_fv` (`fund_financials.investments_at_fair_value`), labelled `investments_ex_cash`.
4. `verified_override` with `basis=investments_ex_cash`.
5. `schedule_total`.

The ledger row gains `anchor_basis` so the acceptance contract and the review queue can show why a
fund flagged. The `agent_investigate` worker prompt states the anchor basis and value; the
add-to-balance instruction ("do not delete to reach a smaller number") is kept only when the basis is
`published_rows`.

**Migration of the 67 existing leaves** (`scripts/backfill_anchor_basis.py`, one-shot, idempotent):
`basis=investments_ex_cash` when `grand_total` is within 0.5% of the leaf's own `companyfacts_fv`;
`basis=published_rows` when `grand_total` exceeds it and at least one component label matches
cash / money market / short-term / treasury; otherwise leave unset and write the CIK-quarter to
`data/output/agent_anchor/basis_backfill_unresolved.csv` for the anchor lane. The script reports
counts per outcome; expected: most of the 59 Q1 leaves classify deterministically.

### 3. Thresholds v3

`data/reference/quarter_acceptance_thresholds.json` version 3, `calibration: provisional`, basis note
"published-basis numerator, 2026-09-07". Existing seven checks unchanged in value. Two added:

| id | metric | op | value | note |
|---|---|---|---|---|
| `over_inclusion_fv_share` | `conservation.over_inclusion_fv_share_pct` | `<=` | 0.5 | FV above anchor across conservation-failed cohort funds, pct of cohort FV |
| `unfinished_investigations` | `investigations.n_stale` | `<=` | 0 | CIK-quarters whose staged rules are newer than their last apply/gate (section 4a) |

`over_inclusion_fv_m` per fund = `fund_fv_m - fund_fv_m / (1 + residual_pct/100)` for ledger rows with
`status=fail` and `residual_pct > 0` (residual is `value_sum/anchor - 1` in pct; with section 1 the
value_sum IS the fund's published FV, so no new ledger column is needed). Summed over the cohort and
divided by `cohort_fv_m`. Undershoots are not counted; they remain in `flagged_fv_share`.

GAV (`validate_holdings`): on `comparison_confidence == STRONG` the BDC bands become WARN outside
[0.98, 1.02] and FAIL outside [0.95, 1.05]. MODERATE/WEAK keep today's 0.8/1.2 and 0.3/5.0. Runner
labels `gav_fail_strong` / `gav_fail_moderate` unchanged.

Surfacing: `fv_conservation` fails on the published basis map to a new surface label
`fv_conservation_fail` (advisory lane) instead of `cons_superseded`. The 2026-06-16 false-positive
assessment was made on the excluding basis; it is re-measured after this ships (section 6) and the
label is revisited only with that evidence.

Expected verification result on Q1 2026 under v3: `over_inclusion_fv_share` FAIL (about 1.07%),
`flagged_fv_share` FAIL (rises above 10% as the cash funds and Bain flag). This is the proof the gate
sees what the forensics saw. The Q1 attestation under v2 stands as a historical record.

### 4. Mechanics fixes

**(a) Stale-apply and stale-gate refusal.** `apply()` writes `rules_fingerprint` (sha256 over the sorted
bytes of `rules/*.json`) into `apply_audit.json`. `gate()` recomputes the fingerprint from the rules
directory and, if it differs from the audit's, returns `verdict: STALE` with the two fingerprints and
the newest rule file name; no checks run. `promote()` already refuses anything but PASS, so STALE is
refused with a reason that tells the operator to re-run apply. Gate JSON and the batch gate summaries
carry `rules_fingerprint`. A new `run_investigation.py audit-stale --quarter Q` lists every CIK whose
rules directory is newer than its `apply_audit.json` or whose last gate record carries a different
fingerprint; `quarter_acceptance` calls it to fill `investigations.n_stale`. PASS_NOOP remains valid
only when the rules directory is empty at gate time; `promote()` on PASS_NOOP with a non-empty rules
directory is a contradiction and refuses.

**(b) Duplicate-add guard widened.** `_existing_position_keys` / `_apply_add` keep the exact
`(report_date, identifier, fair_value)` key and add a second key
`(report_date, fair_value, name_key)` where `name_key` is the issuer name lower-cased, punctuation
stripped, legal-form and share-class tokens removed (llc, inc, corp, lp, ltd, fund, class, shares,
institutional). A candidate row is skipped when its fair value equals an existing row's exactly and
either the token Jaccard of the two `name_key`s is ≥ 0.5 or the existing row is `asset_category=CASH`.
Skips are reported in `rows_skipped_duplicate` as today so `apply_promoted_rules` classifies the rule
`superseded`. The gate's `no_aggregate_addition` uses the same key builder.

**(c) Anchor basis required.** Section 2.

**(d) Quarter-scope carry-over re-test.** In `apply_promoted_rules`, every rule with an explicit
`scope.quarters` list and a predicate (`row_exclusion`, `dedup`, `rescale`, `value_expression`) is also
evaluated against the CIK's rows in quarters NOT in its scope. If it matches, the audit row gets
`drift: scope_carryover` and a message with the matched quarters, row count, and FV. The existing
`promoted_rule_drift` check (`n_drift <= 0`) then fails, which is the point: the rule must be either
extended (edit scope, re-gate, re-promote) or excused by adding
`carryover_reviewed: {"<quarter>": {"verdict": "not_applicable", "evidence": [...]}}` to the rule.
`row_add` rules have no scope filter and are exempt. Rules whose predicate is a hard-coded name list
(Bain's 18 Q4 names) will not match and are not caught here; the basis gate catches those funds.

**(e) CIK padding.** `_apply_add` pads `cik` to 10 digits; `validate_holdings` gains a hard check that
every unified row's `cik` is exactly 10 digits (Q1 today: one unpadded $5.33M TCW Star row splits the
fund across two keys and hides it from the conservation join).

### 5. Data contracts

- Anchor leaf: `basis` required (enum above). Version bump in `anchor_leaf.py`.
- Ledger (`validation_results_ledger.csv`): new column `anchor_basis` appended; `LEDGER_COLUMNS` and the
  test header in `tests/test_quarter_acceptance.py` updated together.
- Promoted-rule audit (`agent_fix_application_audit.csv`): `drift` gains value `scope_carryover`; rule
  JSON gains optional `carryover_reviewed`.
- `apply_audit.json`: `rules_fingerprint`.
- Gate JSON: `verdict` gains `STALE`; `rules_fingerprint`.
- `quarter_acceptance.json`: `conservation.over_inclusion_fv_m`, `conservation.over_inclusion_fv_share_pct`,
  `investigations.n_stale`, per-fund `over_inclusion_fv_m` and `anchor_basis`.
- Thresholds file: version 3.
- Removed: `pipeline/conservation_scope.py`, `config.CONSERVATION_SCOPE_DIR`,
  `agent_rule.CONSERVATION_EXCLUDED_CATEGORIES`, `tests/test_conservation_scope.py`.

### 6. Rollout order (all before the Q2 fleet)

1. Section 4 mechanics (a, b, e) with tests. No data semantics change; safe to land first.
2. Section 1 numerator + shared helper + retire conservation_scope. Section 2 schema + backfill script.
   Section 4d carry-over re-test.
3. Rebuild from cache (`scripts/rebuild_outputs.py --unified`), shadow battery, review queue.
4. Thresholds v3 + acceptance metrics. Run acceptance on 2026-03-31 and re-attest 2025-12-31.
   Record both verdicts in the changelog. Expected: Q1 FAIL on the two FV gates; Q4 result reported
   as measured (Bain Q4 reconciles at 1.002 under the new basis; other funds may move).
5. Re-measure the `fv_conservation` false-positive rate on the Q4+Q1 flagged list (read-only,
   `scripts/shadow_validation_runner.py` output vs anchor evidence). Record in
   `docs/investigations/`; decide the surface label from that number.
6. `python scripts/diff_outputs.py --semantic` against the 2026-09-05 baseline; document deltas.
   Baseline NOT refreshed until the owner accepts the new gate results.

## Testing & verification

- Unit (TDD, each behaviour first observed failing):
  - `published_fv` SQL and pandas agree on a fixture with CASH, `is_subsidiary=1`, added, and unpadded
    rows; engine numerator equals headline for every CIK-quarter in the fixture.
  - Anchor leaf without `basis` rejected; mislabelled basis rejected; backfill script classifies the
    three cases and leaves the fourth unresolved.
  - `companyfacts_fv_plus_cash` candidate used only when CASH rows exist; priority order respected.
  - Over-inclusion metric: fund at +22.4% residual on $2,221.6M contributes $406.5M; undershoot
    contributes 0; share computed against cohort FV; gate fails at 0.51 and passes at 0.49.
  - GAV STRONG bands: 1.03 → WARN, 1.06 → FAIL, MODERATE 1.06 → PASS.
  - STALE: rule file written after apply → gate STALE → promote refused; re-apply clears it.
    PASS_NOOP with rules present → promote refuses.
  - Dup guard: exact-text miss but same FV + Jaccard ≥ 0.5 → skipped; same FV against a CASH row → skipped;
    same FV, unrelated name, non-cash → appended (false-positive test).
  - Carry-over: Q4-scoped exclusion matching Q1 rows → `scope_carryover` drift → acceptance drift check
    fails; `carryover_reviewed` excuses it; `row_add` exempt.
  - CIK padding: 7-digit cik in an add → padded; validation fails on an unpadded production row.
- Integration: `tests/test_agent_rule.py`, `tests/test_agent_promoted.py`, `tests/test_quarter_acceptance.py`,
  `tests/test_shadow_adapter.py`, `tests/test_validate_holdings.py` green; then the unified-holdings file.
- Data: rebuild from cache, battery, acceptance on Q1 and Q4 as in section 6. Report the verdicts as
  measured. Full pytest suite before handoff, in a quiet window, with the diff backstop.

## Risks

- **Flag volume.** Removing the cash and subsidiary exclusions will flag every fund whose anchor is
  ex-cash and holds cash rows (16 in Q1) until candidate 2 or an anchor leaf covers it. Mitigated by
  `companyfacts_fv_plus_cash`; residual load goes to the anchor lane with a declared basis. This is
  the cost of measuring the published number and is accepted.
- **Non-cohort subsidiary funds** (three funds with $1.6B–$2.3B subsidiary blocks) will show large
  overshoots in the wrapped-universe ledger. They are not published; they are flagged, not fixed.
- **Backfill mislabels a leaf.** Bounded by the 0.5% consistency check and by the gate itself: a wrong
  basis produces a residual, not a silent pass.
- **Dup guard over-matches** and skips a real second lot with identical FV (the E10 static-ambiguous
  lot class is 28% of rows). Mitigated: skip requires exact FV equality AND name similarity or a CASH
  counterpart; identical-lot pairs come from extraction, not from `row_add`, so the guard rarely sees
  them. The false-positive test pins this.
- **Q4 re-attest moves.** Funds whose anchors include the subsidiary layer (1633336, 1930087 per the
  2026-08-29 entry) reconcile again; funds where subsidiary rows duplicate the parent will flag.
  Both are correct outcomes; neither is tuned away.

## Acceptance criteria

1. For every cohort CIK-quarter, `conservation.value_sum` in the engine result equals the fund's
   headline FV within $1 (both are DuckDB DOUBLE sums over the same rows).
2. Acceptance on 2026-03-31 under v3 reports `over_inclusion_fv_share` FAIL with Bain, HPS, TCW VII,
   TCW DL, Silver Capital, Fidelity PCF, and GS PCC among the contributing funds.
3. Promotion cannot succeed on a STALE, FAIL, or PASS_NOOP-with-rules gate (tests + one live refusal on
   the HPS staged rules).
4. Re-running `apply_promoted_rules` on Q1 marks the TCW VII dedup rule `scope_carryover` with 27 rows.
5. No anchor leaf without `basis` influences any gate.
6. Zero rows in unified holdings with a non-10-digit `cik`.
