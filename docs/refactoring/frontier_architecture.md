# Frontier Data-Quality Architecture (Design Reference)

Status: design discussion, not yet built. Captures a multi-turn architecture
working session. This is a target to refactor toward, not a description of
current behavior. Where it refers to current code, that is for contrast.

Related: `docs/refactoring/data_engineering_practices.md`,
`docs/refactoring/refactoring_plan.md`, `AGENTS.md` (Agentic Data Quality
Design, Current Product Risk Register).

---

## 0. The organizing principle

One sentence resolves nearly every trade-off below:

> **Deterministic logic decides truth. Learned models decide triage and
> discovery. Statistics decides the published bound.**

Keep those three jobs separate:

- **Determinism for truth** -- production dispositions, field corrections, and
  entity links are decided by versioned, replayable rules and arithmetic gates.
  Auditable; satisfies baseline governance; you can always explain why a $3B row
  was dropped.
- **Learning for triage/discovery** -- ML/agents prioritize the residual queue
  and surface candidate rules, but never decide production truth and never grade
  their own work.
- **Statistics for the bound** -- the published confidence interval comes from
  deterministic gate residuals + materiality-stratified sampling + held-out
  calibration, never from a model's self-reported confidence.

A second principle, equally load-bearing, emerged from the PIK / lien+sector
discussion:

> **Flatten last, not first.** Preserve the full structured source
> representation as the working substrate; the flat, fixed-schema positions
> table is a late, lossy *projection* -- an output, not the source of truth.

---

## 1. Why the current system leaks (the diagnosis)

The current pipeline is strong on reproducibility (write-guard in
`tests/conftest.py`, baseline snapshot/diff, ~1,956 tests) and on
domain-specific source reconciliation (source_reconciliation, wrapper oracle,
FV reconciliation). Those are ahead of typical industry practice.

The weaknesses that let issues "filter through":

1. **Aggregate / disposition semantics are split across ~6 layers** --
   `bdc_identifier` global text rules, `staging_bdc` filters + overrides,
   `bdc_xbrl_wrapper` per-CIK grammar, arithmetic rollup dedup, source
   reconciliation, and validation. No single decision point; precedence is
   implicit.

2. **Reconciliation matches on the wrong key.** The wrapper oracle's
   parent/child search keys on the *dimension string* prefix, not the resolved
   issuer. This is a correctness bug (see the IRGSE worked example) that both
   misses real subtotals and produces false-positive blockers.

3. **No signed residual.** Failures are not classified by sign, so
   "correctly excluded" cannot be distinguished from "wrongly dropped." This is
   why the residual blocker queue is polluted with false positives.

4. **Structure is destroyed early.** Extraction flattens dimensional XBRL into a
   fixed, one-concept-per-row schema. Consumers that need more (position-level
   PIK income/accrual concepts; lien and sector as distinct dimensions) are
   forced to re-read raw XBRL out-of-band (`bdc_position_pik.py`) and re-join on
   a reconstructed identifier string -- as fragile as the format-drift problem
   itself.

5. **No calibrated output and no precision measurement.** Classification is
   spot-audited by an unstratified ~200-position LLM pass, which is not an
   error-rate estimator. There is no per-rule false-positive rate.

Items 1-3 are one failure class (row existence / FV aggregation). Item 4 is a
second class (structure loss) that surfaces repeatedly (PIK, lien, sector,
format drift) from a single root cause. Item 5 is the measurement gap.

---

## 2. The nine-stage architecture

```
            deterministic for TRUTH . learned for TRIAGE . statistical for the BOUND

[0] SOURCE FACTS  (immutable, content-addressed, FULL fact graph)   -- bronze / lineage spine
       |
[1] SIGNAL GENERATION   det. SQL  +  per-CIK wrappers/agents (compile-time, drift-triggered)
       |     every signal: rule_id . rule_type . evidence . raw_confidence
       v
[2] DECISION LAYER     disposition | field-scale | entity-resolution
       |   deterministic policy decides truth  ||  shadow label-model triages
       v
   DECISION LEDGER  (append-only, per axis+key)                     -- the edit/impute record
       |
[3] PROJECTION   unified_holdings = f(facts, ledger)                -- replayable, silver/gold
       |
[4] PROGRAMMATIC GATES   value/conservation  +  structure/format    -- integrity
       |   >0 leak . <0 dropped . ~0 proven   .   block vs flag
       |---------------------------------> residual packets
       v                                          |
[5] CALIBRATION & UQ                         [6] RESIDUAL ORCHESTRATION (active learning)
   gold set . stratified CI .                    agent proposes config -> gate = acceptance test
   conformal coverage check                      -> label written back -> per-rule precision++
       |                                          |
       v                                          v
  published CI + quality tiers              rules grow, queue self-prioritizes, config re-frozen
       |
[7] OBSERVABILITY (drift)  probes "is the taxonomy complete?" -----> new candidate signals
[8] GOVERNANCE / lineage / versioning   (cross-cutting)
[9] SERVING: tiers + CI + provenance -> frontend
```

### [0] Source facts -- immutable, content-addressed, FULL fact graph

Purpose: one immutable layer everything traces to; enables replay, incremental
recompute, and structure-preserving downstream queries.

This is **not** a flat positions table. It is the long-format XBRL fact graph:

```
fact_id | accession | context_id | concept | dim_path{axis:member}
        | value | unit | decimals | period | report_date | form_type
fact_id = hash(accession, concept, dim_path, period, value)
```

Key design decisions:

- **`context_id` is the position-period key.** In XBRL a context binds entity +
  period + dimensional segment, so every fact for one position in one period
  (FV, cost, principal, rate, PIK income, PIK accrual, non-accrual flag) shares
  a context. Joining on `context_id` replaces fragile reconstructed-identifier
  string joins.
- **Preserve all concepts, not a subset.** PIK income/accrual/capitalization
  concepts live next to FV/cost on the same context. Keeping them removes the
  need for out-of-band re-extraction.
- **Preserve the dimensional decomposition.** Lien and sector are distinct
  dimension members for structured filers; only flattened filers jam them into
  one identifier member string.

Options / trade-offs:
- A: fact-level content addressing (recommended) -- per-cell lineage + agent
  cache; costs storage and an ingestion rewrite.
- B: filing-level only (close to today) -- simpler, no per-fact lineage,
  all-or-nothing recompute.
- C: full lakehouse (Iceberg/Delta time-travel) -- overkill for single-node.

Medallion mapping: bronze = this full fact graph; silver = positions assembled
per `context_id` with disposition + normalization applied; gold = the flat
unified schema for index/frontend.

### [1] Signal generation -- many independent producers, no dropping

Purpose: every source row/context accumulates ALL signals; nothing is excluded
yet.

Producers:
- Deterministic, set-based DuckDB SQL: global text rules, arithmetic
  parent/child, dimension-duplicate, scale heuristics, value-domain checks.
- Per-CIK wrapper config (one file per CIK).
- Scoped agents at **compile-time**, cached on filing hash.

**Config lifecycle (refined):** each CIK has ONE config file. It is **frozen**
and edited ONLY when a drift trigger fires (a [4] format-gate failure, or
another drift detector). The agent/compile step does not run every build.

> Safety caveat: a frozen config is exactly as safe as the *recall* of the
> detector that guards it. A drift the detector misses produces wrong data
> indefinitely with a green light everywhere else. Freezing is only sound
> because the [4] format gate watches the grammar.

Relocated producers (previously out-of-band):
- **PIK** (`bdc_position_pik.py`) becomes a signal query over the fact store:
  "for each position-context, are there PIK income/accrual/capitalization
  concept facts?" Joins on `context_id`; no raw re-parse, no identifier re-join.
- **Lien / sector** become signal producers with two paths: read the
  `InvestmentType` / industry dimension member directly (structured filers,
  immune to format drift), else parse the identifier string (flattened filers,
  guarded by the format gate).

Every signal carries: `rule_id`, `rule_type in {deterministic, arithmetic,
heuristic, agent}`, `evidence`, `raw_confidence`. The `rule_type` field lets
later stages treat signals differently instead of as one blob.

Options / trade-offs:
- A: agents author per-CIK config at compile-time (recommended) -- replayable
  runtime, amortized cost; needs a cache-invalidation discipline.
- B: agents in the runtime loop -- maximal adaptivity; nondeterministic, slow,
  violates no-network/reproducibility.
- C: pure rules, no agents -- fully deterministic; undercovers the long tail.

### [2] Decision layer -- where determinism vs autonomy is settled

Purpose: resolve signals into ONE terminal decision per (axis, key) across three
axes -- disposition, field-scale normalization, entity resolution -- recorded in
the ledger.

The pivotal choice:
- A: deterministic ordered resolution policy (named priority ladder, e.g.
  non_private_market > duplicate_dimension > subtotal > comparative > include).
  Auditable, replayable, governable; brittle to novel patterns; precedence is
  hand-designed.
- B: weak-supervision label model (Snorkel-style) -- learns each signal's
  accuracy without ground truth, emits a probabilistic disposition. Adaptive;
  but a black box deciding material truth, nondeterministic, ungovernable.
- C (recommended): hybrid -- deterministic policy decides production truth; the
  label model runs as a SHADOW that (i) prioritizes the residual queue and
  (ii) flags rows where learned-confidence disagrees with the deterministic
  decision as candidates for a missing rule.

Sub-decisions:
- **Disposition** must keep ALL firing signals; only the terminal label is
  single. Comparative/temporal status is a SEPARATE axis (`period_role`:
  current/comparative), not a value in the disposition enum -- a comparative row
  can independently be a position or a subtotal, and comparatives are legitimate
  prior-period facts, not garbage.
- **Entity resolution**: upgrade from union-find on normalized names to
  probabilistic record linkage (Fellegi-Sunter / Splink) producing match
  *probabilities* (feed the CI), with a fixed threshold for the production link.
  This is the one discipline the current design does not yet adopt, and it is
  the weakest-gated axis.
- **Scale / normalization**: apply the Fellegi-Holt minimal-change principle --
  when a value fails an edit (rate < 1 but peer median 8.5), impute the smallest
  change that satisfies all edits (x100), recorded as a correction with
  evidence, checked by the income-reconciliation gate.

`rule_type` distinguishes deterministic vs heuristic vs arithmetic vs agent so
confidence is not conflated across decision kinds.

### [3] Projection -- unified_holdings as a pure function

`unified_holdings = f(source_facts, decision_ledger)`, deterministic and
replayable. The flat fixed-schema row (one per position, with `lien_position`,
`pik_rate`, sector columns) is GOLD -- a lossy convenience view, derived not
authoritative. No consumer that needs structure reads it; they read the fact
store.

Options: materialize with a content hash (recommended; same inputs -> identical
output = baseline governance for free) + incremental recompute keyed on changed
CIK-quarters; or view/recompute on read.

### [4] Programmatic gates -- TWO families

The oracle is purely programmatic (no agent can satisfy a gate by editing its
own output). There are two distinct families:

| Family | Reconciles against | Catches | Blind to |
|---|---|---|---|
| **Value / conservation** | independently-tagged FV total | subtotals, dup dimensions, dropped positions | format drift (FV unchanged) |
| **Structure / format** | prior-quarter grammar fingerprint + field value-domains | parse-grammar drift, column shifts | value errors |

**Value/conservation gate**: reconstruct an aggregate from the projection and
reconcile to an independently-tagged source aggregate. Signed residual:
`>0` over-inclusion (leaked subtotal/dup); `<0` over-exclusion (dropped real
position -- the false-positive class); `~0` disposition set proven complete.
Matching MUST be on resolved issuer + value across ALL axes, never on dimension
string prefix.

**Structure/format gate**: detects per-CIK grammar drift via (a) arity
fingerprint, (b) field value-domain signatures (e.g. an industry field now
holding "First Lien", an instrument-type token), (c) cross-quarter grammar
fingerprint diff. Conservation is blind to this because FV is unchanged. This
gate is ALSO the drift detector that triggers the [1] config edit -- it does
double duty.

Gate registry shape: each gate = `(reconstruction_query, independent_target,
tolerance, blocking, fallback)`.

Members: FV conservation (top-level), sub-aggregate by resolved issuer, income
reconciliation (loose), magnitude anchor (GAV / prior-quarter continuity --
catches filer-wide scale), chain-continuity invariants, format gates,
context->position cardinality.

Options / trade-offs:
- Tolerance: fixed; **materiality-scaled (recommended)** -- tight on large FV,
  loose on immaterial; or statistical rounding model.
- Missing target: block; or **degrade-to-flag-and-tier (recommended)** -- never
  a silent pass when no independent total exists.

Coverage = union of anchors. Gates cover only anchored quantities; publish the
anchored-FV fraction, do not imply universal coverage.

### [5] Calibration & uncertainty -- the published number

Construct the published number as `X_true = X_reported + sum_i E_i`, one error
term per class, NEVER blended:

1. **Deterministic residual** (gate-covered FV): for passing CIK-quarters the
   error is bounded by tolerance tau -- a hard bound, not a probability.
2. **Sampled CI** (loosely-anchored classes -- classification, rate scale,
   identifier collapse): materiality-stratified random audit, source-grounded
   labels, Wilson/Clopper-Pearson rate CI, Horvitz-Thompson ratio estimator for
   FV-weighted propagation.
3. **Unanchored exposure** (no gate, no practical sample): bound the FV share,
   report as a ONE-SIDED non-probabilistic risk, carved out -- not folded in.

Error is tail-dominated (one missed $3B subtotal swamps thousands of correct
$30M positions), so tight intervals come from materiality-stratified
near-census of material FV, not clever statistics.

Calibration is EARNED, not asserted: maintain a held-out gold set independent of
the gates; measure empirical coverage with a reliability diagram; recalibrate if
nominal != empirical. Conformal prediction gives distribution-free coverage
under exchangeability (errors are not exchangeable across filers -> stratify).

The CI is always conditional on the enumerated error taxonomy + the carved-out
unanchored exposure. An unconditional "X +/- 0.2%" is not achievable and would
violate the anti-overstatement contract.

### [6] Residual orchestration -- the autonomy loop

Active learning: prioritize the queue by `materiality x P(real) x
signal-disagreement`. The agent receives a localized packet (signed residual,
candidate rows, arithmetic / format evidence) and proposes a DETERMINISTIC
config/rule change with mechanism + evidence + confidence. The gate re-run is
the acceptance test; accept iff residual -> 0 AND baseline diff shows no
regression. Every resolution (true or false positive) writes a label -> grows
the gold/truth set -> updates per-rule precision -> sharpens triage.

Agent-authority options:
- A: propose-only, human merges -- safest, slowest.
- B (recommended): auto-merge under guardrails -- gate-accepted, scoped to one
  CIK, proposing rule-class precision above threshold, baseline diff clean.
  Graduated autonomy; this is "as autonomous as possible" without the agent
  owning truth.
- C: full auto -- fastest, riskiest.

Maker-checker holds because the validator is programmatic and independent of the
proposer.

### [7] Observability -- the only probe of taxonomy completeness

Lightweight in-repo statistical drift checks (volume/distribution/schema per
CIK-quarter) surface error classes not in the taxonomy (new filer, new axis,
FV-magnitude jump, concept drift). Without this, the calibrated CI stays
"conditional on taxonomy completeness" with nothing actively testing the
condition. Build in-repo rather than SaaS (no-network posture).

### [8] Governance -- cross-cutting

Immutable lineage from every published cell back to `(fact_ids, signal_set,
rule_ids, gate_results, tier)`. Versioned rules/config with schema versions and
effective-from accession. Baseline snapshot/diff retained. Tests as the
regression net. Maker-checker on baseline refresh. Tiers and CIs always carry
conditionality.

### [9] Serving -- show the uncertainty

Frontend consumes quality tiers (verified / preliminary / under-review /
unanchored / stale) + the CI + a known-limitations list, with provenance
drill-down. Show uncertainty; do not polish it away.

---

## 3. Schemas

### 3.1 Source fact store (bronze)

```
fact_id          TEXT  -- hash(accession, concept, dim_path, period, value)
cik              TEXT  -- 10-digit zero-padded
accession        TEXT
context_id       TEXT  -- XBRL context: entity + period + dimensional segment
concept          TEXT  -- e.g. InvestmentOwnedAtFairValue, *PaidInKind*Income*
dim_path         JSON  -- {axis: member, ...}, e.g. {InvestmentIdentifierAxis: "..."}
value            DOUBLE
unit             TEXT  -- e.g. USD, shares
decimals         INT   -- XBRL scale hint
period           DATE  -- the fact's own period (may be a comparative)
report_date      DATE  -- filing's primary period
form_type        TEXT
filing_date      DATE
raw_identifier   TEXT  -- verbatim identifier member string, never normalized here
```

A position-period is the set of facts sharing one `context_id`. PIK / FV / cost
/ rate are different `concept` rows under it.

### 3.2 Decision ledger (append-only)

```
decision_axis    TEXT  -- disposition | field_scale | entity_resolution | classification
key              TEXT  -- axis-specific: fact_id | (fact_id,field) | cluster_id | context_id
terminal_label   TEXT  -- include_position | exclude_subtotal | exclude_comparative
                       --   | exclude_duplicate_dimension | exclude_non_private_market
                       --   | document_source_rollup | review_blocker | (axis values)
period_role      TEXT  -- current | comparative   (SEPARATE from disposition)
signals          JSON  -- ALL firing signals (not just the winner)
rule_id          TEXT  -- the responsible rule/config
rule_type        TEXT  -- deterministic | arithmetic | heuristic | agent
evidence         TEXT
confidence       DOUBLE
blocking         BOOL
child_output_ids JSON  -- if a documented rollup, the children it reconciles to
```

### 3.3 Gate registry

```
gate_id              TEXT
family               TEXT  -- value_conservation | structure_format | continuity | magnitude
reconstruction_query TEXT  -- SQL producing the reconstructed aggregate / fingerprint
independent_target   TEXT  -- the source fact / prior-quarter reference to compare against
tolerance            TEXT  -- absolute/relative, materiality-scaled
blocking             BOOL  -- strong -> block; weak -> flag + tier
fallback             TEXT  -- behavior when no independent target exists (degrade-to-flag)
```

---

## 4. Worked examples

### 4.1 IRGSE -- conservation gate + signed residual (CIK 0001508655, TSLX)

Source facts (2023-06-30) include affiliation-axis lines and type-axis tranches:
- type axis: `Debt Investments ... IRGSE Holding Corp. First-lien loan (...)
  Interest Rate 14.86%` FV $30,034,000; `... First-lien revolving loan ...
  14.92%` FV $21,456,000; plus further tranches.
- affiliation axis: `Controlled Affiliated Investments IRGSE Holding Corp.`
  FV $66,654,000 (= sum of the tranches); `Controlled Affiliated Investments`
  FV $66,654,000 (IRGSE is the only affiliated issuer).

Current behavior: the affiliation lines are NOT proven subtotals (no marker for
"controlled affiliated investments"); they are dropped by leaf-signature failure
and then RE-FLAGGED as `missing_from_pipeline`. The oracle reported
`candidate_source_child_count = 0` because it searched children under the
*dimension-string* prefix `...Controlled Affiliated Investments IRGSE...`, while
the real tranches live under `...Debt Investments Hotel, Gaming and Leisure
IRGSE...`. So this is simultaneously a correctly-excluded subtotal AND a
false-positive blocker.

Frontier behavior:
- Issuer-level gate: `FV("...IRGSE Holding Corp." affiliation line) ==
  sum(IRGSE tranche FVs)` matched on RESOLVED ISSUER across axes -> the
  affiliation line is a rollup of rows already in the output -> exclude and
  auto-clear the missing flag. No marker, no agent.
- Top-level gate: with tranches in and subtotals out, `sum(leaves) == Total
  Investments`, residual 0 -> the disposition set is proven complete. The single
  identity validates the whole set without a per-row rule.
- The agent (if needed) proposes a STRUCTURAL rule
  ("affiliation-axis issuer line reconciling to its tranches under any axis =
  rollup"), not a per-string marker; the gate is the acceptance test.

Lesson: signed residual distinguishes leaked-subtotal (overshoot) from
wrongly-dropped (undershoot); resolved-issuer matching is mandatory.

### 4.2 ABC Corp -- format gate + drift-triggered config edit (CIK 0000123456)

Frozen config v3: pipe-delimited, 3 fields `[0]=issuer [1]=rate [2]=industry`.

- Q1: `ABC Corp | 2.00% | Technology`, FV $50M -> parses clean.
- Q2: `ABC Corp | 2.00% | First Lien | Technology`, FV $50M -> 4 tokens.

Trace:
- [0] Q2 fact ingested, content-addressed, raw identifier stored verbatim.
- [1] config v3 applied; deterministic parse yields industry="First Lien"
  (wrong). Signals: `arity_drift=true` (4 vs 3), `field_signature_violation
  (industry)=true` ("First Lien" in instrument-type vocab). Config NOT edited.
- [2] disposition = include_position (correct); field axis records
  industry="First Lien" with a `format_drift` flag, low confidence.
- [3] row materialized with the wrong industry + drift flag.
- [4] conservation gate PASSES (FV unchanged -- blind). Format gate FAILS:
  arity 3->4 for this CIK, industry signature pass-rate collapse, "First Lien"
  is instrument-type. Emits a drift packet. THIS packet triggers the [1] edit.
- [5] affected rows drop to "under review" for classification; FV CI untouched.
- [6] agent proposes config v4: 4-field variant
  `[0]=issuer [1]=rate [2]=instrument_type [3]=industry`, variant-selected on
  token count, effective-from Q2. Acceptance test: re-parse Q2 -> signatures
  pass, format gate PASS, conservation still PASS, baseline diff shows only
  corrected fields. Merge under guardrails; re-freeze. Label written (format
  gate TP).
- [7] per-CIK token-count monitor confirms "arity drift" is a known class.
- [8] v3->v4 versioned with effective-from accession + evidence; v3 retained.
- [9] rows return to "verified" once gates are green; shown "under review" in
  the interim.

Lesson: format drift is a class conservation cannot see; it needs its own
anchor (grammar fingerprint + value-domains), and that anchor is the trigger
that unfreezes the per-CIK config.

### 4.3 PIK / lien+sector -- structure preservation (flatten last)

Root cause shared with format drift: early flattening to a fixed,
one-concept-per-row schema discards sibling concepts (PIK income/accrual) and
the dimensional decomposition (lien, sector). Today `bdc_position_pik.py`
re-reads raw XBRL and re-joins on a reconstructed `matched_identifier`.

Frontier placement:
- [0] fact store preserves ALL concepts + `context_id` + dim members.
- [1] PIK becomes a signal query joining on `context_id` (key join, not string
  re-join). Lien/sector become signal producers reading dimension members for
  structured filers (immune to format drift), string-parsing only for flattened
  filers (format-gated).
- [3] the flat schema with `lien_position`, `pik_rate`, sector is a GOLD
  projection, derived not authoritative.

Lesson: PIK, lien, sector, and the format gate are the same wound (early
flattening). One decision -- bronze keeps the full fact graph, flatten last --
retires the whole class; no out-of-band re-extractors remain.

---

## 5. Coverage, autonomy ceiling, and what passes a perfect gate

A gate only catches errors that perturb the quantity it reconciles. Coverage =
union of independent anchors.

Passes a perfect FV-conservation gate while still wrong:
- FV-neutral substitution (keep a subtotal, drop an equal-value position).
- Filer-wide scale (whole schedule read in ones not thousands -- ratio
  preserved). Needs an external magnitude anchor (GAV, prior-quarter).
- Rate scale (8.5 vs 0.085). Needs income reconciliation (loose proxy).
- Classification (private credit vs hedge fund). Needs fund-strategy
  cross-check (weak/flag).
- Identifier collapse across quarters. Needs continuity invariants (weak).

Honest ceiling: this is NOT fully autonomous, and no honest version is. The
ceiling is set by anchor availability, not cleverness. "As autonomous as
possible" reduces to three measurable objectives:
1. Maximize the FV share under deterministic anchors (census material FV).
2. Make the residual queue self-prioritizing (signed residual + learned triage).
3. Auto-calibrate continuously against an independent gold set.

The largest improvements are corrective and statistical (fix the gate key,
measure precision, calibrate), not handing the agent more authority.

---

## 6. Where this sits vs current and vs best practice

Best-practice stack borrowed from five fields: declarative checks-as-code
(Great Expectations / dbt / Deequ), control-total reconciliation (financial DW /
regulatory reporting), data observability (Monte Carlo / Anomalo -- weak
checks), medallion + lineage (Iceberg/Delta, OpenLineage), weak supervision
(Snorkel), probabilistic record linkage (Fellegi-Sunter / Splink), survey
sampling + acceptance sampling + conformal prediction, and -- the closest single
precedent -- Fellegi-Holt automatic editing & imputation at national statistical
institutes (deterministic edit rules + minimal-change imputation + published
margin of error, separating sampling error from non-sampling error).

- Currently AHEAD of typical industry: reproducibility governance, per-CIK
  config externalization, domain source reconciliation.
- Currently BEHIND: scattered logic, reconciliation key bug, no signed residual,
  structure destroyed early, no calibrated output, no precision tracking,
  heuristic (not probabilistic) entity resolution.
- The frontier design MATCHES or EXCEEDS best practice on most axes (the per-row
  decision ledger is ahead of standard practice) and DELIBERATELY steps back
  from learned signal combination for production truth (deterministic for
  auditability), using learning only for triage/discovery.

---

## 7. Suggested build order (80/20)

1. **Stages 0 + 2 + 3 (ledger + projection) and fix the [4] gate to
   resolved-issuer matching.** Centralizes scattered logic, kills IRGSE-class
   false positives via signed residuals, makes the build replayable. Largest
   correctness gain for least work.
2. **Stage 6 minus auto-merge** (propose-only loop + per-rule precision). Turns
   the polluted blocker queue into a self-prioritizing one.
3. **Stage 5 (gold set + stratified CI).** The publishable confidence number --
   credible only once 1-2 are solid.
4. **Stage 2 probabilistic entity resolution** and **Stage 7 drift**. Closes the
   last discipline gap and probes taxonomy completeness.

Sequence the structure-preservation work (full fact graph in [0], flatten last
in [3]) alongside step 1, since PIK and lien+sector both depend on it and both
have active fixes in flight.

---

## 8b. Step 1 (v1) -- shadow disposition ledger (BUILT)

Script: `scripts/build_shadow_disposition_ledger.py` (read-only; writes only to
`data/output/shadow/`). Run: `PYTHONPATH=. python scripts/build_shadow_disposition_ledger.py`.

Scope: the 77 wrapped BDC CIKs (10-digit configs in
`data/overrides/bdc_xbrl_wrappers/`), current-period rows only
(`period == report_date`). Interim fact source is `bdc_holdings`.

Design (REVISED -- do not re-derive disposition logic). v1 does NOT build a
competing disposition engine. It REUSES the existing pipeline's disposition
outcome (a row is a position iff it survived the full validated rule stack into
`private_markets_holdings`, joined on `(cik, report_date, bdc_dimensions_raw ==
dimensions_raw)`). The only NEW thing v1 adds is the independent programmatic
conservation gate over that existing output: `Sum(included FV) - Total
Investments` fact, per CIK-quarter. Cheap text/marker/leaf signals are kept ONLY
as high-recall/low-precision triage flags (`leak_candidate`, `drop_candidate`),
never as decisions. (An earlier draft built fresh competing signals; it lost to
the validated logic in both directions and was abandoned -- the months of
trial/error in the existing rules are the asset, not a thing to reimplement.)

Outputs: `bdc_row_disposition_ledger.csv` (existing disposition + triage flags),
`bdc_triage_summary.csv`, `bdc_conservation_residual.csv` (the gate result).

First-run findings (2026-06-15, 316,379 rows / 77 CIKs / 850 CIK-quarters;
288,208 included / 28,171 excluded by the existing pipeline):

1. **The gate over the EXISTING output is the real product.** On the 155
   tight-anchored CIK-quarters: 67 reconcile (within 0.5%), 37 overshoot/leak
   (real leaked subtotals still present in the validated output), 51
   undershoot/missing (dropped or absent positions). ~88 CIK-quarters is the
   genuine residual queue, found with zero reinvented logic.

2. **Anchor repointed to `fund_financials` (companyfacts) -- coverage ~18% ->
   ~90%.** The conservation anchor now uses
   `fund_financials.investments_at_fair_value` (the SAME quantity as
   Sum(positions), from the independent companyfacts API) as the STRONG tight
   anchor, the schedule grand-total as a secondary tight anchor, and
   `fund_financials.total_assets` as a loose bound. Coverage of the 850 wrapped
   CIK-quarters: companyfacts_fv 734, schedule_total 34, loose_assets 9, none 73
   (~90% tight-anchored). Validation: median `sum_included / tight_anchor = 1.0`;
   and where companyfacts_fv and the schedule grand-total BOTH exist (n=121) they
   agree to 0.0% median |diff| -- two independent sources triangulating the
   anchor. Gate over the existing output: 452 reconcile, 204 overshoot/leak, 112
   undershoot/missing -> a ~316-CIK-quarter residual queue.

3. **`bdc_fund_highlights` balance-sheet fields are broken AND unused; do not use
   them.** Substring-bound `total_assets`/`total_liabilities`/
   `stockholders_equity` satisfy the balance-sheet identity only 4.3% of the
   time (Sixth Street 2023-12-31 shows $7.6M for a $3.28B fund). The companyfacts
   path (`fund_financials`) satisfies it 98.8% and is the single source of truth
   for the balance sheet. See `data/output/data_investigation_results.md`
   (2026-06-15). The broken highlights fields feed nothing in production; they
   are being removed from the highlights extraction.

4. **Where an anchor exists, the existing rules largely reconcile** (Sixth
   Street 0001508655 2023-12-31: +0.027% on $3,283M). The existing scattered
   logic is the validated asset; the refactor REUSES it and only adds the gate +
   ledger + provenance on top.

5. **The `leak_candidate` flag is high-recall/low-precision** (41K rows /
   ~$845B, mostly real positions whose detail lives in the identifier string).
   It is a triage net, not a verdict; the gate's `tight_overshoot_leak` is the
   precise signal. Making the flag precise needs the resolved-issuer arithmetic
   signal.

Next v1.x steps: (a) extract the balance-sheet `InvestmentOwnedAtFairValue`
no-dimension total to lift tight coverage beyond ~18%; (b) fix the highlights
`total_assets` scale to unlock the loose bound anchor; (c) localize each
`tight_overshoot_leak` / `tight_undershoot_missing` to specific rows via the
resolved-issuer arithmetic signal; (d) Phase 2 -- instrument the existing
staging/wrapper code to EMIT `rule_id` + evidence into the ledger (preserve the
logic, add provenance) rather than reconstructing the outcome.

## 8. Open questions / risks to resolve before building

- `context_id` is not edge-case-free: comparative periods rotate contexts, and
  some filers split one economic position across multiple contexts (debt +
  equity tranches; affiliation-axis duplication, the IRGSE pattern). Needs a
  context->position cardinality gate.
- Held-out gold set maintenance is a recurring human tax; size drives both
  CI tightness and calibration credibility.
- The deterministic-vs-learned boundary in [2] must be a conscious, documented
  choice per axis; the recommended default is deterministic-for-truth,
  learned-for-triage.
- Filer-wide scale and FV-neutral substitution need explicit anchors; they are
  NOT covered by FV conservation.
- Frozen per-CIK config is only as safe as the drift detector's recall --
  invest in format-gate coverage accordingly.
```

## 9. Wrapper split (Part A / Part B) and identifier-flattening prevalence

The wrapper skill splits into two MODES over ONE per-CIK config (not two skills,
not two configs):

- **Part A -- deterministic parse + enrich.** Runs IN-PIPELINE, downstream of the
  xbrl / ixbrl / html extraction. For FLATTENED filers it splits the composite
  `investment_identifier` (per-CIK pipe/grammar rules, as the current wrapper
  already authors) into issuer / instrument / rate / maturity / etc. and enriches.
  For STRUCTURED filers it reads the dimension members directly -- string-splitting
  is the flattened-filer FALLBACK, and the format gate guards that grammar (trips
  on column drift). Config is frozen until a drift trigger fires.

- **Part B -- agentic review of the shadow validation-results ledger.** Consumes
  the unified tier-tagged ledger (all engines/columns), triages each residual:
  (i) parse/enrichment defect -> author a new Part A rule; (ii) genuine source-data
  error -> escalate (no rule); (iii) scope / known-exclusion -> document
  non-blocking. Proposes audited config (mechanism/evidence/confidence); the gate
  (ledger re-run) is the acceptance test. Agents discover; the gate decides.

  > **Bundle construction requirement (measured 2026-06-16, see
  > `bundle_enrichment_experiment.md`).** Part B review bundles MUST inject the RAW
  > current-period source rows for the filing (identifier + FV + match-status, unparsed),
  > not derived signals. Derived enrichment (resolved coordinate candidates, deterministic
  > issuer arithmetic) is CIRCULAR -- it presupposes the broken parse that creates the
  > blocker -- and does not help. Raw rows let the agent locate the issuer by reading and
  > reconcile FV itself; in a paired trial this flipped indecisive verdicts
  > (ESCALATE/INSUFFICIENT) to decisive NO_PATCH/HIGH with zero regressions. Also keep the
  > `source_only_blocker_rows` snapshot FRESH: several blockers were already matched
  > (match_status='matched') or issuer rollups, needing no patch -- a stale snapshot
  > inflates the INSUFFICIENT queue.

Execution loop (Part A must RUN before Part B can validate):
    A runs -> engines compute the ledger -> B validates -> B authors a Part A rule
    (defects only) -> A re-runs -> ledger re-validates.
Part B's FIXES land in Part A's config because the durable fix to a parsing defect
IS a Part A rule, and there must be one source of truth for "how this CIK's
identifiers are parsed." Validation (reading the ledger) writes nothing.

### Flattening prevalence (measured 2026-06-15, current-period BDC, CIK counts)
- FLATTENED (rate embedded in investment_identifier): 74 CIKs (~38%) -- need the
  string parsed for rate/maturity/instrument.
- STRUCTURED (typed rate field, clean identifier): 75 CIKs (~39%) -- datapoints
  from separate XBRL facts.
- MIXED / equity-heavy (no rate): 45 CIKs (~23%).
Per-datapoint source (all current-period rows): identifier carries a rate% in
26.6%; typed interest_rate filled 59%; typed maturity_date filled only 29% (so
maturity is predominantly string-sourced even for structured filers); identifier
has due/par 30%; median identifier length 62 chars. FV-weighting omitted -- raw
bdc_holdings FV is pre-dedup and inflated. Conclusion: identifier parsing (Part A)
is load-bearing for ~half the universe, and maturity_date broadly.
