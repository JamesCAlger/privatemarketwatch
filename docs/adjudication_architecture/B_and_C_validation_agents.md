# Validation Agents B (Adjudicator) and C (FN Probe) — Architecture Spec

Status: substrate + B0/B0.5/B1 pilot built (45-bundle trial run, 2026-06-18, under
`data/output/shadow/trial_2026-06-18/`); B2/B3/B4 and Agent C not yet built. This
consolidates the design discussion into a buildable spec; current defaults for all
open decisions are resolved in Section 10.

## 0. Purpose and scope

The shadow ledger (`validation_results_ledger.csv`) already *produces* warns and
blockers deterministically. It does not *adjudicate* them (is a given flag a real
data defect or an artifact of the check?), and it cannot measure what it *missed*
(false negatives). This spec defines two agents that close those two gaps:

- **B — Adjudicator.** Decides, per flagged unit, whether the flag is a real
  error, a false alarm, or genuinely ambiguous; localizes the culprit where that
  is well-posed; and (downstream) proposes a deterministic fix that is gated by a
  re-run of the deterministic rules.
- **C — FN Probe.** Samples the *un-flagged* population and adjudicates it to
  estimate the false-negative rate per grain, and to discover missing rules.

Both are subroutines inside a deterministic pipeline, not autonomous owners of the
truth (per `AGENTS.md`). The deterministic layer does as much as it can; agents
operate only on the residual it cannot resolve.

Guiding evidence from prior work in this repo:

- **Bundle-enrichment v3** (`6f1487b`, `c52f7df`): agents reconciling *derived*
  signals fail; raw-source injection works. Verdicts must close on raw source.
- **full-filing-search-adjudication** (memory): a verdict is only as independent
  as the rawness of what the reviewer can interrogate; build one shared
  cached-filing search primitive used by BOTH the gold harness and the agents.

## 1. The localization taxonomy (the organizing principle)

Every rule in the registry sorts into one of three localization classes, and the
class determines how much work the agent does and what kind. The illustrative
examples below name the original shadow-engine + oracle rules; the full measured
tally over the ~272-rule registry is in section 1a.

### Class 1 — Single-cell localized (~25-30 rules, ~1/3)

"This one value looks wrong" -> one (row, column) cell. Essentially the entire
field-validity family:

- weak format-contract rules (~15-20): per-cell range (`interest_rate in [0,25]`,
  `fair_value`, `pik_rate`, `cost`, `principal_amount`, `shares_held`,
  `pct_of_net_assets`), enum (`exposure_type`, `asset_class`, `coupon_type`,
  `reference_rate_type`), string-length (`issuer_name`, `entity_name`), pattern
  (`cik`), date-parse (`report_date`, `maturity_date`).
- `pct_position_concentration`, `maturity_not_past`.
- rate/scale per-position suspects (rate in (0,1) or > 50% -> the `interest_rate`
  cell).
- single-cell F-series: `F01`, `F04`, `F07`, `F09`, `F11`, `F12`, plus `I09`.

### Class 2 — Row-localized, not single-cell (~15-20 rules, ~1/3)

Points at a row; *which* field is wrong is ambiguous or spans cells. Needs
within-row context to decide:

- `pik_le_interest_rate` (2 cells), `pct_of_net_assets_identity` (FV vs pct vs
  net_assets — any of three), `F03`/`F08` (sign/dup), `A01` subtotal arithmetic,
  `B02`/`I11` dup keys, `B08` comparative, `C05` rate-on-equity,
  `G01`/`G02`/`G03` aggregate/subtotal/header, `I02`/`I06` markers, `J04`.

### Class 3 — Aggregate / fund-level, not position-localized (~30-35 rules, ~1/3)

The flag is a property of the whole CIK-quarter; there is no row to point at:

- `fv_/cost_conservation`, all 8 `cross_source` rules, fund-scalar identities
  (`nav_`, `income_`, `balance_sheet_`), `dl_rate_fill`, wavg-coupon +
  income-recon, `A04`/`A07`, `B01`/`B07`, `C01`/`C04`/`C08`, all D-series, all
  E-series, H-series, `I08`/`I10`, most J-series match-rate checks.

### The core asymmetry

Localization and judgment are **inversely related**:

- Class 1 is highly localized but the deterministic check is already
  near-conclusive (a rate of 0.05 amid a column of 5-15 is almost certainly a
  scale error). The agent adds little *diagnostic* value — but see 4.1: it still
  adds *measurement* value, because we do not yet know any rule's precision.
- Class 3 most needs judgment but offers no localization at all. This is where the
  "any grouping that sums to the gap" vs "row-by-row with an equality oracle"
  problem lives, and it is the hardest third.

The agent's required work per class:

| Class | Agent task | Context needed | Primary value |
|---|---|---|---|
| 1 single-cell | confirm a known cell | column distribution (+ source for the cell) | measure rule precision |
| 2 within-row | decide which field / whether real | the full row + source row | adjudication |
| 3 aggregate | classify rows -> partition; route mechanism | per-row context, fanned out | adjudication + localization |

## 1a. Measured registry pass (2026-06-18) — corrects the earlier estimate

The earlier "~80 rules, even thirds" estimate was wrong on both counts. A pass over
the actual registry found:

- **Scale.** The shadow ledger (`validation_results_ledger.csv`) is a UNION of the
  four shadow engines + the oracle + several adapter-ingested suites
  (`validation_rules` ~95, `fund_financials` F1-F34, `row_validation` ~41,
  `source_recon`, `html_extract`, `gav_recon`, `fund_strategy`, `nonaccrual`,
  `aggregate_header`, `classification`, `derivative_role`). The snapshot read had
  **229 distinct `(engine, rule_name)`** with a PARTIAL oracle (only 5 of 48
  J-series rows present). The oracle's 48 A-J checks ARE ingested under
  `engine='oracle'` by `shadow_adapter.py` (`_oracle_select`); they were just not
  fully materialized in that snapshot. Fully wired the registry is **~272 rows**.

- **No dedup, by design.** The ledger does not deduplicate semantically
  overlapping checks. NAV identity exists on >=3 paths (`identity.nav_identity`,
  `fund_financials.F11`, oracle `E04`); GAV recon on >=3 (`gav_recon`, oracle
  `A04`/`E01`, native `conservation`). These differ by source/anchor/tolerance/
  grain and are kept as independent corroboration — agreement raises confidence,
  disagreement is itself signal (the input to the `corroborated` confidence
  class). Consolidation happens downstream (review_queue grouping + confidence
  scoring), never by mutating the ledger. So "~272 rows" overstates the number of
  distinct *checks*; there is real cross-engine redundancy, partly principled
  (different source/tolerance) and partly accreted tech debt (separate suites
  built at different times). Retiring a proven-redundant check is a MEASURED
  engine-level retirement (see section 9), not a ledger dedup.

- **The split is not even thirds — it inverts toward the hard end.** Aggregate
  (Class 3) is the LARGEST class (~40%+), single-cell (Class 1) second (~30%),
  within-row (Class 2) smallest (~25%). (Directional; the per-rule classification
  still needs a verified pass — the first automated pass over-assigned Class 2 by
  lumping fund-level strategy rules `S01-S10` and cross-quarter temporal rules
  `T01-T10`/`IDX*` there when they are aggregate.) This STRENGTHENS the core
  asymmetry: the hardest, least-localized class (conservation / cross_source / the
  equality-oracle problem in 4.2) is the biggest slice of the work, not an equal
  third.

Producing the exact, calibrated per-rule class tally is folded into the trial run
(section 9), because the same adjudication pass that measures rule precision also
fixes the grain labels.

## 2. Shared substrate

Neither agent owns this; both depend on it.

**Evidence library** — cached-filing search primitives in
`pipeline/html_soi_evidence.py`, the only path to raw data:

- `search_filing(cik, accession, query)` -> IDF-ranked rows with coordinates.
- `extract_anchored(cik, accession, context_id)` -> the one SOI row for an XBRL
  fact.
- `extract_total_fv(cik, accession)` -> the filing's own grand-total line (the
  independent anchor).
- `extract_issuer_narrative(...)` -> prose for classification calls.
- all return `(table_index, row_index, cell_indices, context_id)` — the same
  coordinate contract the human gold harness uses (calibration coupling).

**Independent anchors** (read-only): cached companyfacts
(`InvestmentOwnedAtFairValue/Cost`, `total_assets`, `net_assets`, NAV),
`fund_financials`, highlights, `bdc_fund_income`.

**Hard contracts** (both agents):

- read-only on all production artifacts; append-only to own output dir;
- cached-only, NO SEC network (escalate on cache miss, never fetch; download is
  the gated `--allow-html-download` step, owned upstream);
- ASCII logs; never trigger a rebuild (no duplicate long-running jobs).

**Verdict leaf schema** (shared vocabulary, so outputs are comparable and
calibratable):

```json
{
  "verdict": "real_error | false_alarm | ambiguous",
  "mechanism": "subtotal_leak | dimension_double_count | comparative_leak | unit_scale | rate_scale | anchor_bad | genuine_value_defect | extraction_gap | classification_lookthrough | unknown",
  "localized": true,
  "culprit_citations": [{"table_index": 0, "row_index": 0, "cell_indices": [0], "context_id": "", "quoted_text": "", "ties_to_residual": true}],
  "anchor_used": "companyfacts_fv | schedule_total | extract_total_fv",
  "observed_value": 0, "anchor_value": 0,
  "confidence": 0.0,
  "escalate": false
}
```

Invariant: **`real_error` requires either >=1 `culprit_citation` OR an explicit
anchor-disagreement proof. No raw grounding -> forced `ambiguous`.**

## 3. The no-haystack constraint (applies to both agents)

The agent must **never** be handed a large set and asked to find a needle. That
fails three ways: recall collapses and is unmeasurable (it checks a few rows and
stops); it substitutes invented heuristics (re-implementing a deterministic rule
badly); and for most rules there is no clean oracle to iterate against.

Therefore, in this design:

- **Localization is done deterministically or recast as classification — never as
  agent search.** Either the deterministic layer hands the agent a single located
  item, or the task is reframed as per-row classification (every row labeled, a
  census, recall measurable).
- **The agent's unit of work is always one bounded, context-rich item** — the
  gold-review motion. Breadth is achieved by fanning out many bounded
  adjudications, not by one big-context scan.
- **Anything that would require searching a large set is handled upstream
  deterministically or escalated** — never delegated to the model as a scan.
- The `search_filing` primitive enforces this: it is targeted query-with-
  coordinates, not a dump. The anti-pattern is pasting holdings rows into the
  prompt.

## 4. Agent B — Adjudicator

Consumes the flagged population (the shadow list). Pipeline:

```
bundle -> B0 intake -> B0.5 grain/class router
       -> B1 adjudicate ─ false_alarm -> rule-scoping queue (fix the CHECK)
                        ─ ambiguous    -> human
                        ─ real_error   -> B2 remediate (templated, trial wrapper)
                                       -> B3 re-run gate (full oracle, all quarters, held-out)
                                       -> B4 promote
```

This per-bundle pipeline runs INSIDE an outer, dependency-ordered loop (Section 4.3):
B processes rules in dependency-tier order (Tier 0 = FV conservation first) and
regenerates the full error set between tiers, so a downstream rule is adjudicated only
after its upstream prerequisites are settled.

### B0 — Intake

One `review_bundles/{review_id}.json` per invocation: flag,
`source_artifact_rows`, `holdings_slice`, coordinates, `evidence_completeness`.

`evidence_completeness in {ledger_only, artifact_missing}` -> short-circuit to
`ambiguous`/escalate (fail-closed; no raw source to adjudicate against). NOTE:
`artifact_missing` is a **coverage** state, not an adjudication state — track its
proportion as a coverage KPI and resolve it upstream (caching), distinct from the
source-reconciliation blocker pool, which presumes source already exists.

### B0.5 — Grain / class router

Route by the Section 1 class:

- **Class 1 (single-cell):** location given. Adjudicate the cell with its column
  distribution + source. Purpose is mostly precision measurement (4.1).
- **Class 2 (within-row):** row given. Adjudicate which field / whether real, with
  the full row + the source row.
- **Class 3 (aggregate):** no location. Do NOT search a haystack. Apply 4.2.

Cross-class shortcut: an aggregate (Class 3) flag can *inherit* a location by
joining to a co-located row-grain flag on `(cik, report_date)` (e.g. a `G02` hit
supplies the subtotal row for a `conservation` overshoot, and the residual is the
cross-check).

### B1 — Adjudicator (the gold-validator analog)

- **Anchor triangulation first** (Class 3 especially): `extract_total_fv` (filing
  total) vs companyfacts anchor vs position sum. This separates `real_error` from
  `anchor_bad` WITHOUT row-finding — the minimum valid verdict.
- Localize when well-posed (find the culprit whose FV ties to the residual) to
  assign a confident `mechanism`. Do not gate the verdict on localization — a
  diffuse defect (e.g. scale error across many rows) is still `real_error` with a
  coarser mechanism.
- Skeptic-by-default; defaults to `ambiguous` on missing/unclear source. For
  high-FV blockers, run a 3-vote panel (majority + surfaced disagreement); single
  pass for cheap items.
- Emits verdict JSONL -> `data/output/review_queue/verdicts/`.
- **`false_alarm` -> rule-scoping queue** (fix the *check*, evidence-backed; never
  edit data to silence a flag). This is the most important routing rule: writing a
  data-fix for a false alarm corrupts good data.

### 4.1 Class 1 — adjudicate ALL to learn per-rule precision

We have no measured precision for any rule; the ledger `confidence` column is a
heuristic bootstrap classification, not empirical. So:

- **Bootstrap phase: census / heavy sample across ALL rules** — do not pre-trust
  any rule, including "obvious" single-cell ones.
- **As a rule's precision stabilizes (narrow Wilson CI), throttle to a maintenance
  sample** (drift watch). Stratified-by-rule sampling sized to a target CI width.
- **Census forever only for rules feeding an enforcement gate** — there each
  instance is a production decision, not just a metric.
- Output: a **per-rule precision table** through the gold apparatus, which then
  *replaces* the heuristic confidence column and becomes the prior that sets
  routing (95%-precision rule -> light scrutiny; 40% -> stays in census, candidate
  to rewrite or demote).

### 4.2 Class 3 — conservation via per-row classification, not residual search

The naive options both fail when keyed off the residual `R = position_sum - anchor`:

- "provide any grouping of rows that sums to R" is **subset-sum**: exponential AND
  non-unique (with 4000 rows, astronomically many subsets total ~R by
  coincidence; no signal).
- "free rein, iterate until the two numbers are equal" is **gameable by deletion**
  (drop legitimate rows until it balances). The current wrapper process "works"
  only because a human supplies the judgment the bare equality oracle lacks.

The fix is to **invert the driver**: localize by *structure*, not by R; or recast
as per-row classification. Concretely, the chosen design:

1. **Deterministic first pass.** `bdc_row_disposition_ledger.csv` already labels
   each row (`is_total`, `bare_header`, `flag_explicit_aggregate`,
   `leak_candidate`, `drop_candidate`). This auto-resolves the high-confidence
   majority.
2. **Agent on the residual rows only.** Per-row classification
   (subtotal/aggregate vs genuine position) on the `leak_candidate`/
   `drop_candidate`/ambiguous rows, each with raw-source context. This keeps the
   census property (every row ends labeled) while bounding agent calls to the
   uncertain minority — not 4000.
3. **Conservation becomes a consistency check on the labels, not the search
   objective.** Test `sum(rows labeled position) == anchor`. Equality is *emergent
   evidence the labeling is right*, never the thing being optimized — which
   eliminates deletion-gaming, because the agent labels each row on its merits and
   never "removes to balance."
4. **The labeling outcome routes the mechanism for free:**
   - subtotals found whose removal closes R -> `subtotal_leak`, localized.
   - everything labeled "position", subtotals absent, R remains -> `anchor_bad` or
     `extraction_gap` (missing rows) — *not* a localization failure.
5. **Companion axis check for `dimension_double_count`.** Per-row subtotal
   labeling does NOT catch a legitimate position counted twice via two XBRL axis
   paths (each instance looks valid row-by-row). Pair the classifier with a cheap
   deterministic axis/duplicate check for that mechanism.

Genuine discrete-rows residual where structure finds nothing and it is not
diffuse (rare): the iterate-against-oracle path, but only under the **full B3
gate** (not bare equality), and kept human-in-loop or high-confidence-panel — this
is the wrapper-authoring regime.

Bonus: the per-row labels are gold-grade. Audited against a human sample they (a)
give the empirical precision/recall of the deterministic disposition labeler, and
(b) every subtotal the agent catches that the rules missed is a new
structural-pattern candidate for B2.

### B2 — Remediator (the wrapper-author analog)

Only `real_error`, **grouped by mechanism** (one rule covers many bundles, not one
edit per bundle). Each mechanism binds to a **constrained rule template** (scale
factor, aggregate regex, dimension-axis drop, period filter) — auditable JSON,
never free-form code (per `AGENTS.md`: per-CIK corrections as audited config, not
growing global keyword lists). Writes the proposed rule into a **trial** wrapper
(`rebuild_unified_cik_trial.py`), cached-only.

Mechanism -> layer routing (Open Decision 1 governs global vs per-CIK):

| mechanism | template | re-run regression watch |
|---|---|---|
| subtotal_leak | aggregate pattern / wrapper `aggregate_marker` | `G02`/`D03` |
| unit_scale / rate_scale | per-CIK scale rule | `F01`/`F12` + rate-scale gate |
| comparative_leak | fix `B08` (global), not per-CIK | all quarters |
| dimension_double_count | dimension-path dedup | conservation residual -> 0 |
| extraction_gap | parse/coverage rule | `H01` coverage |
| classification_lookthrough | per-CIK classification override (audited JSON) | `S11` re-run, all quarters |
| (false_alarm) | scope the validation rule; NO data edit | check-precision delta |

### B3 — Deterministic re-run gate (the strong check)

The check B cannot satisfy by editing its own output. Re-run the FULL oracle/
ledger on ALL quarters of the CIK. Promote only if jointly:

- target flag cleared, AND net flags across the CIK non-increasing, AND
- FV-at-risk non-increasing AND residual moved *toward* the anchor (not just a
  status flip), AND
- counts/FV stay within `D01`/`D02` bands (catches delete-to-balance), AND
- held-out quarters not regressed (catches single-quarter overfit; Open Decision 2
  sets how many quarters).

Fail -> reject + escalate.

### B4 — Promotion

Human promotes the staged rule; or auto-promote under materiality tiers (P0 =
$25M/1%, P1 = $5M/0.25%) with the gate green. B never edits production directly.

### 4.3 Rule processing order -- dependency tiers and the serialized loop

Errors are not independent. A defect in the FV population (`subtotal_leak`,
`dimension_double_count`, a missing row) propagates into every downstream metric that
reads FV or row membership: `pct_of_net_assets`, GAV recon, fund-strategy mix shares,
the S11 look-through `credit_share`, `cross_source`, income yield. Adjudicating a
downstream rule before its upstream prerequisites are settled measures it against
contaminated inputs and spends scarce LLM adjudication on symptoms that disappear once
the upstream fix lands. So B processes rules in dependency order and regenerates the
error set between tiers.

This is DISTINCT from the Section 9 measurement pass (which samples ALL rules at once
to learn precision). Section 9 is the diagnostic that PRIORITIZES; this loop is the
canonical REMEDIATION cadence. They coexist (4.3c).

#### 4.3a Dependency DAG (tiers; a partial order, not 1..N)

| Tier | Rules (illustrative) | Why upstream |
|---|---|---|
| 0 population / denominator | FV+cost conservation (`subtotal_leak`, `dimension_double_count`, `extraction_gap`/missing-row), row disposition | sets WHICH rows exist and the totals everything reads |
| 1 FV-derived ratios | `pct_of_net_assets` identity, GAV recon | functions of the Tier-0 FV/row set |
| 2 classification & strategy | `S01-S10`, `S11` look-through, classification cross-reference | mix shares / look-through composition computed from corrected holdings |
| 3 rate / income / cross-source | rate-scale, income-yield, `cross_source`, NAV/income identities | per-position values, read once FV is trustworthy |

Tier 0 is the operator-specified #1: FV matching (subtotal leaks / missing rows)
finalizes before anything else, because the rest inherit its row set and totals. Edges
are dependency, not strict sequence -- rules with no downstream dependents (per-cell
rate-scale, date-parse, enum-validity) are independent and may finalize in parallel at
any time. The exact per-rule tier assignment is produced/verified by the same trial
pass that fixes the grain labels (9.5 item 4); the table is the directional default.

#### 4.3b The serialized loop

```
pick the highest unfinalized tier
  -> B1 adjudicate + B2 remediate ALL firing CIKs for that tier's rules
  -> B3 gate each fix (per-CIK, all quarters)
  -> REGENERATE the full shadow ledger deterministically from corrected holdings
     (cached rebuild; no network, no LLM)
  -> re-triage the residual: flags that were symptoms of the upstream defect dissolve
     here, BEFORE they cost an adjudication
  -> advance to the next tier
```

"Rule finalized" (the gate to advance) = jointly: (i) its B2 templates promoted across
all firing CIKs or explicitly escalated; (ii) measured precision at/above its target CI
(4.1 / 9.4); (iii) the post-regeneration re-run shows the rule's RESIDUAL is genuine,
not an artifact of an unsettled upstream tier.

Termination: B3 already requires net flags AND FV-at-risk non-increasing per fix
(B3 gate), so the loop monotonically shrinks the blocking pool and converges. A fix
that creates net-new flags is rejected by B3 and never promoted, so regeneration cannot
cycle.

#### 4.3c Effect on measurement (amends Section 9)

Section 9's precision numbers become TIER-CONDITIONAL. Run the all-rules sample once to
prioritize; then re-measure each tier's rules on the regenerated ledger after the prior
tier finalizes, so a downstream rule is never credited or blamed for upstream
contamination. The per-rule precision table (9.5 item 1) carries a "measured-after-tier"
column. Re-run granularity is governed by Decision 6.

## 5. Agent C — FN Probe

Consumes the un-flagged population. Materially different task (open-ended
detection, not confirm/refute), so a **separate skill** sharing the substrate but
with its own objective and calibration. Pipeline:

```
quality tiers (preliminary/unverified) -> C0 PPS sample
   -> C1 deterministic probe sweep ─┐
   -> C2 LLM residual detection ─────┤ -> C3 confirm (terminal)
                                      -> C4 route ─ FN metric (HT/Wilson)
                                                  ─ new-rule queue -> B2
   -> C5 estimate
```

### C0 — Frame

Sample from `validation_quality_tiers.csv` `preliminary`/`unverified` tiers (the
`silent_bulk` population), **PPS-weighted by FV**, grain-specific (position /
CIK-quarter / dimension). Record inclusion probability `pi` per unit for the
Horvitz-Thompson estimator. Deliberately under-sample `verified` (already cleared
an independent anchor). Sample only dimensions no aggregate check covers (don't
sample CIK-quarters for FV-conservation FN — conservation already covers anchored
quarters).

### C1 — Deterministic probe sweep (before any LLM)

Re-apply the engines' own predicates to the sampled un-flagged units (run `G02` on
a CIK that *passed* conservation; check identity residuals just under threshold).
Cheap, strongest evidence, does the haystack search so the LLM never does.

### C2 — LLM residual detection

Only on units the probes cannot render a verdict on, and only as **bounded
single-item** judgments ("is THIS one position mis-extracted, given its
context?") — never "scan this CIK's 4000 positions." The no-haystack constraint
applies in full; breadth comes from fan-out.

### C3 — Confirm

Each candidate confirmed against raw source + anchor using B1's discipline. This
adjudication is **terminal**.

### C4 — Route (the single convergence point; no loop)

A confirmed FN goes to (a) the FN-rate metric and (b) the new-rule-candidate queue
for B2. It does **not** round-trip to B — C already found and adjudicated it.

### C5 — Estimate

Horvitz-Thompson FV-weighted FN rate + variance; Wilson CIs for unweighted rates;
per stratum and per quality tier. Feeds the frontend quality tiers (is
`unverified` genuinely risky or merely uncovered?).

## 6. Calibration layer (shared apparatus, separate statistics)

Both feed `scripts/gold/review_harness.py` + `scripts/gold/estimate_gold.py`:

- B calibrated on flagged precision (+ suppressed-FN among its `false_alarm`
  calls) and the per-rule precision table (4.1).
- C calibrated on detection `e_FP`/`e_FN` (a different error profile — do not
  pool).
- A single ~200-unit human tail census can physically cover units for both, but
  `e_FP`/`e_FN` and the **Rogan-Gladen** correction
  (`r = (r_agent - e_FP)/(1 - e_FP - e_FN)`) are computed per task.
- Agent outputs carry `label_status: agent_candidate`; human `human_confirmed`.
- Until the human slice exists, both produce **relative** numbers ("relative to
  agent"); the slice converts them to absolute with widened CIs. The gold set is
  not a prerequisite to start; a ~200-unit human audit is the prerequisite for the
  number being absolute rather than relative.

## 7. How B and C relate

| | B | C |
|---|---|---|
| Input | flagged units (`review_queue`) | un-flagged sample (PPS by FV) |
| Task | confirm/refute located claim | open-ended detection |
| Output | verdict + (optional) trial rule | confirmed FN + FN estimate |
| Calibration | flag precision | detection e_FP/e_FN |
| Shared | evidence library, anchors, verdict leaf schema, B3 gate, B2 Remediator, gold apparatus |

Parallel and contention-free: disjoint inputs, read-only production, append-only
to separate dirs (`verdicts/` vs `fn_probe/`). Launch concurrently. Single
feedback edge: both B's `real_error` and C's confirmed FN flow into the
Remediator/new-rule queue; C never enters B, so there is no loop.

The honesty boundary: deterministic gates (B3 re-run, C1 probes) certify
*internal* consistency; the human gold slice is the only thing tying any of it to
filing truth. Keep both — a self-consistent system with no human anchor is exactly
how you end up confidently wrong about the filings.

## 8. Worked addition — fund-interest look-through classification check (S11)

This section specs one concrete Class 3 check end to end (new detector -> B1 -> B2
-> B3), both because it is a known live defect and as the worked template for
adding any new classification-grade rule to the ensemble. It is the per-holding
look-through check: a FUND/JV interest whose underlying holdings are predominantly
loans should be `PRIVATE_CREDIT_FUND`, not `PRIVATE_EQUITY_FUND`.

### 8.0 The defect, and why nothing currently catches it

Concrete case: `BCRED Emerald JV LP` (CIK 0001803498), an LP-interest position
~$1.7B, ~3.5-5% of net assets, tagged `index_classification=PRIVATE_EQUITY_FUND` /
`asset_class=PRIVATE_EQUITY` from report_date 2024-09-30 on. The underlying loans
inside the JV (rows like `Smile Doctors, LLC, Emerald JV LP` -- borrower name first,
JV name as suffix) are correctly `DIRECT_LENDING` / `PRIVATE_CREDIT` (310 such loans
at 2024-12-31, 100% credit). It is a private *credit* JV mislabeled private
*equity*. The
platform is position-level, so this single misclassified FUND interest mis-buckets
~$1.7B of credit exposure as equity.

No existing check fires:

- **Fund-strategy S01-S10** are fund-level mix thresholds. BCRED is ~94% direct
  lending, so `private_credit_share` ~0.94 (FS02 needs <0.50), `fund_of_funds_share`
  ~0.031 (FS03 needs >0.30), dominant strategy stays PRIVATE_CREDIT (FS04 needs a
  flip). A ~4% misclassified JV cannot move any fund-level threshold. PASS every
  quarter.
- **Classification cross-reference (I-series)** checks only *axis internal
  consistency*. `PRIVATE_EQUITY_FUND` and `PRIVATE_CREDIT_FUND` both map to FUND
  exposure, so I3 and its siblings are satisfied either way. No I-rule distinguishes
  the two FUND sub-types.
- **weak `index_classification`** is an enum-validity check; `PRIVATE_EQUITY_FUND`
  is a valid enum value -> passes.

So this is presently a **false negative** (Agent C territory). S11 converts it to a
deterministic flag that Agent B owns.

### 8.1 The detector (deterministic, Class 3, position-targeted)

S11 fires on a FUND-interest position whose declared class disagrees with the
look-through composition of its attributable underlying holdings, OR, where that
composition cannot be computed, marks it for narrative adjudication. Two paths,
decided by coverage (this is the chosen "composition + narrative fallback" basis):

**Subject set.** Positions with `asset_category=FUND` (LP/member/JV interests) and
`index_classification in {PRIVATE_EQUITY_FUND, PRIVATE_CREDIT_FUND, REAL_ESTATE_FUND,
HEDGE_FUND}`. (UNCLASSIFIED/OTHER fund interests are a separate coverage gap, not a
misclassification.)

**Attribution rule (the join).** Underlying rows for a JV interest named `X` are the
same-CIK, same-quarter rows whose `issuer_name` contains the JV name. Measured on
BCRED, the JV name appears as a SUFFIX, not a prefix: interest `BCRED Emerald JV LP`
<- underlying `<borrower>, Emerald JV LP` (e.g. `Smile Doctors, LLC, Emerald JV
LP`). So the join is contains/normalized-token match, and the exact form
(prefix/suffix/token) is per-CIK config -- filers name JV sub-portfolios
differently. The detector records `lookthrough_row_count` and
`lookthrough_fv_coverage = sum(attributed FV) / abs(interest FV)`.

NOTE -- coverage is NOT bounded at 1.0. The interest FV is the fund's NET EQUITY
stake; the attributed underlying is the JV's GROSS assets, which for a levered JV
exceed the equity (BCRED Emerald 2024-12-31: $5.6B gross underlying vs $1.78B equity
interest -> coverage = 3.16). Treat `COVER_MIN` as a floor that confirms "underlying
is actually ingested," NOT a "% of the interest explained." The decisive signal is
`credit_share` (1.00 for BCRED Emerald: 310 underlying loans, all PRIVATE_CREDIT),
not coverage.

**Path A -- composition (coverage adequate, `lookthrough_fv_coverage >= COVER_MIN`).**
Sum attributed underlying FV by `asset_class`; compute `credit_share`,
`equity_share`, `re_share`. Fire if the declared FUND sub-type contradicts the
dominant look-through class -- e.g. declared `PRIVATE_EQUITY_FUND` but `credit_share
>= CLASS_MIN`. Deterministic, high-confidence; payload carries the shares + row
coordinates. This is the BCRED path.

**Path B -- narrative fallback (coverage inadequate).** Where underlying holdings
are not ingested (e.g. Ares SDLP: the JV's loans sit in a separate supplemental
schedule the pipeline does not ingest, so `lookthrough_fv_coverage` ~ 0), the
detector CANNOT decide by composition. It emits a lower-confidence `needs_narrative`
flag carrying the interest row + filing coordinates, deferring the
credit-vs-equity call to B1 against issuer prose. It does **not** guess from the
name.

Tier: weak/advisory at emit (like S01-S10); it earns enforcement weight from the
9.x precision pass, not by fiat. Engine: extends `fund_strategy_validation.py` but
operates at *position* grain (the JV interest row), unlike the fund-level S01-S10 --
flag that grain difference explicitly so B0.5 routes it as locatable.

### 8.2 B0.5 routing

Class 3 by nature (fund/classification-level), but unlike conservation it **has a
located subject**: the FUND-interest row itself. So it skips the 4.2 per-row-
classification machinery -- there is no subset-sum problem, the culprit row is
given. Route as "Class 3 with inherited location," adjudicate the one row.

### 8.3 B1 adjudication

- **Path A:** triangulate three independent signals -- declared class, look-through
  composition (the structural anchor, from the attributed underlying rows), and
  issuer narrative (`extract_issuer_narrative` on the JV's description / formation
  language). `real_error` when composition AND narrative agree against the declared
  class; `ambiguous` when they disagree (a genuinely mixed JV); skeptic default.
  Mechanism `classification_lookthrough`. Culprit citation = the interest row + the
  strongest underlying rows.
- **Path B:** narrative only. `extract_issuer_narrative` -> credit-vs-equity /
  fund-vs-operating-company call with the discipline already used for the SDLP /
  Ivy Hill findings. No composition to lean on, so the bar for `real_error` is an
  explicit prose anchor ("the Company invests in senior secured loans of ...");
  absent that -> `ambiguous` -> human. Lower confidence than Path A by construction.

Requires extending the verdict-leaf `mechanism` enum (section 2) with
`classification_lookthrough` (done).

### 8.4 B2 remediation

Mechanism `classification_lookthrough` -> a **per-CIK classification-correction
template** (audited JSON, never a global keyword): bind `(cik, issuer_name pattern)`
-> corrected `index_classification` + `asset_class`. Per-CIK by Decision 1 -- a JV's
identity is filer/entity-specific, not a cross-CIK pattern. Writes into the trial
wrapper; one template can cover the entity across all its quarters.

Optionally surfaces a structural-pattern candidate ("FUND interest whose look-through
is >=X% credit -> PRIVATE_CREDIT_FUND" as a *global* rule), but only via the
Decision-1 promotion bar (>=3-5 unrelated CIKs, filer-independent, full regression).
Do not start global.

### 8.5 B3 gate

Classification has no numeric residual like conservation, so the gate is structural:

- Re-run S11 on ALL quarters of the CIK: the correction clears the flag on every
  quarter the entity appears with credit look-through, AND stays inert on quarters
  where the entity is absent or genuinely equity (the held-out / not-overfit test of
  Decision 2).
- Net classification flags across the CIK non-increasing; the correction flips ONLY
  the targeted interest (and, if intended, its parallel rows), not unrelated FUND
  positions.
- FV moves between asset_class buckets as expected (credit bucket up by the interest
  FV, equity bucket down) and the CIK's `D01`/`D02` count/FV bands hold.
- Power floor (Decision 2): <2 quarters with the entity -> allowed but
  `unvalidated_cross_quarter`, human-routed, never auto-promoted.

### 8.6 Measurement and relationship to Agent C

S11 enters the 9.x trial as a new rule: census in bootstrap (no prior precision),
its own Wilson-CI precision row, unique-coverage counted (does it catch real errors
no other rule does -- it should, by 8.0). Its existence is itself an Agent-C finding
promoted to a deterministic rule: every FUND-interest misclass S11 now catches is
one fewer FN for C to rediscover. Confirmed S11 misses (a credit JV it failed to
flag because coverage was low AND narrative was thin) remain C's to find and route
back as detector refinements.

### 8.7 Scope, thresholds, and false-positive guards

- **Coverage dependency.** Path A only exists where underlying holdings are
  ingested. The platform-wide ingestion gap for JV supplemental schedules (SDLP-type)
  is a coverage KPI, not an S11 defect; track the `lookthrough_fv_coverage`
  distribution.
- **Do not over-fire.** A JV that genuinely holds equity must stay
  `PRIVATE_EQUITY_FUND`; a mixed JV is `ambiguous`, not an auto-correction. The
  composition threshold exists precisely so a 55/45 split does not flip.
- **Open thresholds (owner to set, then freeze before the trial):** `COVER_MIN`
  (look-through FV coverage to trust Path A; suggest >=0.60), `CLASS_MIN`
  (dominant-class share to assert a contradiction; suggest >=0.70). These are the
  only free parameters; record them in config, measure precision at the chosen
  values in 9.x, tune from data not intuition.

## 9. Trial-run measurement plan — rules as a measured ensemble

### 9.0 Goal

Reframe the whole rule set as a **measured ensemble classifier**: each rule's
fire/no-fire is a binary feature, the adjudicated verdict is the label, and we
learn which rules (and rule combinations) actually predict real errors. This
replaces the current heuristic `confidence` column (a bootstrap classification,
not empirical) with measured per-rule and per-combination predictive power. The
trial is run over the FULL rule set (do not pre-exclude any rule — we know no
rule's precision yet), but on a SAMPLE of the population, not a census.

### 9.1 What B and C each measure (do not conflate under "recall")

- **B, on the flagged set, yields per-rule PRECISION** = P(real error | rule
  fired). Naturally per-rule, well-powered for high-frequency rules.
- **C, on the un-flagged set, yields RECALL / FN at the SYSTEM level.** Per-rule
  recall is only estimable after attributing each confirmed FN to "the rule that
  should have caught it," and is low-powered for rare error types (the PPS sample
  may contain few or none). So: per-rule precision (good power), system recall/FN
  (good power), per-rule recall ONLY for common error types.

### 9.2 "Good predictor" = lift — measured by counting, not by a fitted model

A rule with precision 1.0 that fires once predicts nothing; a rule that fires on
everything has recall 1.0 and precision ~= base rate. Score each rule by **lift
over base rate** (or F-score), and — the real prize — find high-lift
**combinations** (`conservation_fail AND G02 AND D03` beats any single rule). The
key point: all of this is **count-based and collinearity-robust**; a fitted
parametric model is optional and only needed for a narrow case (9.2c).

**9.2a — Primary analysis: empirical conditional precision (just counting).**

- **Per rule (marginal):** for each rule, count fires and real-among-fires;
  divide. This is computed independently per rule, so the cross-engine redundancy
  of section 1a does NOT distort it. This is what drives promote/demote.
- **Unique coverage (marginal):** for each rule, count cases where it fired, was
  real, and no other KEPT rule fired. Zero correct solo-fires + low precision =
  the evidence to **retire** it (e.g. `identity.nav_identity`); a correct solo-fire
  = unique recall, keep it (e.g. oracle `E04`).
- **Per observed fire-pattern:** stratify on the exact set of rules that fired and
  count precision per pattern. This captures corroboration directly ("all three
  NAV paths fired" gets its own empirical precision, typically >> any single path)
  and is also pure counting — no credit-splitting.

These three counts answer every rule-disposition question (promote / demote /
retire / composite-gate candidate) without fitting anything.

**9.2b — Why NOT lead with a fitted lift model.** A logistic-style model with one
coefficient per rule, read as "rule importance," breaks under the section-1a
collinearity: when overlapping checks fire together, the data constrains only the
SUM of their coefficients, so the optimizer splits credit between them arbitrarily
(regularization / noise) and can label a perfect predictor "worthless" because its
twin absorbed the weight. Marginal precision (9.2a) never does this; coefficients
do. So coefficients are not a valid importance ranking here.

**9.2c — When a fitted model is actually required.** Only to score an UNOBSERVED
combination: with ~272 rules the fire-pattern space is astronomically larger than
the sample, so most patterns are never seen and cannot be counted. If a single
fused P(real) score over arbitrary patterns is wanted, fit a model THEN — with
collinearity controls (group correlated rules, regularize, or add a derived
"N-of-k agree" feature). This is a generalization tool, never the importance
ranking.

Output: a per-rule precision + unique-coverage + lift table and a per-fire-pattern
precision table, both count-based with CIs; an optional fused model only if 9.2c
applies.

### 9.3 The load-bearing caveat: labels are agent-made

B and C emit ADJUDICATED labels, so every number is "predictive of what the agent
decided," not of truth. **Circularity trap:** if the agent's blind spots correlate
with the rules' blind spots (likely — both reason over the same artifacts), rule
quality is overstated. Mitigations, mandatory:

- A small human gold slice (~200-unit tail census, section 6) measures the
  adjudicator's `e_FP`/`e_FN`; **Rogan-Gladen** converts agent-relative numbers to
  truth-relative with widened CIs.
- C's recall is bounded by C's own detection ability (it cannot find errors no
  method sees). Report the FN estimate as a **lower bound on misses** / upper
  bound on recall, never as absolute truth.
- Until the human slice exists, label every output "relative to agent."

### 9.4 Sampling and power (sample, not census)

- Run over ALL rules; sample the population. Size each rule's sample to a target
  Wilson CI width on its precision. High-frequency rules converge fast; the long
  tail of once-firing rules cannot be measured and is reported as such (no false
  precision).
- C draws PPS-by-FV from `preliminary`/`unverified` tiers (section 5).
- This is the bootstrap phase of 4.1: heavy/census now, throttle per rule as its
  CI narrows.

### 9.5 Outputs and what they unlock

1. **Per-rule precision/lift table** (replaces the heuristic `confidence` column);
   tier-conditional -- measured on the post-upstream-tier regenerated ledger (4.3c).
2. **High-lift rule combinations** -> candidate composite gates.
3. **System-level recall/FN estimate** per grain and quality tier -> frontend
   quality tiers; confirmed FNs -> new-rule queue (section 5).
4. **Verified grain-class tally** (fixes section 1a; the adjudication pass relabels
   grain as a by-product).
5. **Rule-disposition decisions, evidence-backed:** promote high-lift rules to
   blocking gates; demote low-lift rules to advisory; **retire proven-redundant
   duplicates** at the engine level (NOT by ledger dedup) once two paths are shown
   collinear and one adds no independent lift.

### 9.6 Procedure

1. Freeze the registry snapshot; fully materialize the oracle (so all 48 A-J are
   present, not 5).
2. Draw the flagged-set sample (per-rule sized) and the un-flagged PPS sample.
3. Run B over the flagged sample, C over the un-flagged sample, in parallel
   (section 7) — read-only, cached-only, no rebuilds.
4. Hand-label the ~200-unit human gold slice covering units from both.
5. Compute per-rule precision + unique-coverage + per-fire-pattern precision
   (Wilson, count-based; 9.2a) + Rogan-Gladen correction; HT FN estimate. Fit the
   optional fused model only if scoring unobserved combinations is needed (9.2c),
   with collinearity control.
6. Emit the section-9.5 artifacts; record rule-disposition decisions with the
   metric before/after and the evidence.

## 10. Decisions (recommended defaults; owner may override)

1. **Mechanism -> fix layer. RESOLVED: default per-CIK; global only on cross-CIK
   evidence + full regression.** Asymmetry: a too-narrow per-CIK fix leaves other
   CIKs unfixed (visible, reversible); a too-broad global fix silently corrupts
   other CIKs (invisible, dangerous) -- so bias to per-CIK (per AGENTS.md). A fix
   lives at the layer where its mechanism is invariant:
   - Filer-format mechanisms (subtotal labels, identifier layout, scale convention,
     dimension paths) stay per-CIK regardless of frequency -- cross-CIK "sameness"
     is coincidental, not structural.
   - Filer-independent mechanisms (comparative `B08`, date-parse, enum mapping) are
     global candidates.
   - Promote a per-CIK template to global ONLY if all hold: (i) the identical
     template independently resolved real_errors across >=3-5 unrelated CIKs (the
     9.x cross-CIK precision data is the trigger), (ii) the mechanism is
     filer-independent by definition, (iii) it passes the FULL regression suite
     (all CIKs), not just one CIK's held-out quarters.

2. **Held-out definition. RESOLVED: all other quarters of the CIK; >=2 required to
   auto-promote.** Not a fixed number -- the held-out/regression set is every other
   quarter that CIK has. Refinements:
   - "Not overfit" = correct behavior BOTH ways: clears the defect on held-out
     quarters that should exhibit it, and stays inert on quarters that should not.
     A rule that only ever fires on the source quarter is overfit by construction.
   - Power floor: <2 held-out quarters (new filer) -> fix allowed but flagged
     `unvalidated_cross_quarter`, lower confidence, routed to human, never
     auto-promoted.
   - Era weighting: include pre-XBRL HTML quarters in the re-run, but treat a
     regression on a template-extracted pre-2022 quarter as lower-confidence
     evidence than one on an XBRL-era (~2022+) quarter.

3. **Rule-class tally.** Section 1a gives the measured directional split (Class 3
   largest); the exact, verified per-rule grain labels are produced as a by-product
   of the trial run (9.5 item 4).

4. **Redundancy counting (trial). RESOLVED for the primary analysis:** count-based
   conditional precision (9.2a) treats each path as its own feature and is
   collinearity-robust, so no choice is forced. The once-vs-per-path question only
   reappears IF the optional fused model (9.2c) is built, where it drives the
   collinearity control. Defer until/unless 9.2c is invoked.

5. **Gold-slice timing. RESOLVED: run trial first, target the draw, label blind**
   (the before/after binary is false -- decouple WHICH units from WHAT is shown):
   - Run the trial first to get agent verdicts + confidence.
   - Draw the gold slice with a targeted, REWEIGHTABLE stratified design
     (oversample low-confidence / disagreement-prone / high-FV); record inclusion
     probability per stratum for HT/Wilson reweighting.
   - Present each unit to the human BLIND (agent verdict hidden) -> unbiased ground
     truth -> compute `e_FP`/`e_FN` per stratum, reweight, Rogan-Gladen.
   - Include a small UNIFORM blind slice alongside the targeted one as the
     circularity guard (9.3) against an error class the agent+rules jointly miss.

6. **Re-run granularity (the serialized loop, 4.3). RESOLVED: regenerate at TIER
   boundaries, not per leaf rule.** Regenerating the deterministic ledger is cheap; LLM
   re-adjudication is not. So batch the independent rules within a tier, regenerate the
   full error set once at the tier boundary (and after any individual rule that is
   upstream of others), and re-triage before descending. Shrinking the residual before
   re-adjudicating is the saving; gratuitous full re-runs after leaf rules with no
   dependents are pure cost. The dependency DAG (4.3a) defines which rules are
   "upstream of others." Tier 0 (FV conservation) is always finalized first.
