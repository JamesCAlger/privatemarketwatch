# Handoff — Stand up the minimum-viable gold-set apparatus (design + harness + first sample; do NOT mass-label yet)

Status: design brief for a new agent. Stop for human review at the four deliverables below.
Do not begin large-scale labeling until the design is approved.

---

## Task

Build the minimum viable **source-adjudicated gold set** apparatus for the v1 BDC
enforcement panel, under a solo-operator constraint (one human labeler; human
bandwidth is the binding resource, so the design must minimize it).

## Why

The shadow validation panel (`scripts/shadow_validation_runner.py` +
`scripts/shadow_quality_tiers.py`) currently emits an **honest proxy** — a
confidence/surface tag derived from independence signals, with **no measured
precision or recall**. A source-adjudicated gold set is the only thing that can:

1. **Measure per-rule precision**, so the enforcement registry can widen past its
   deterministic day-one floor instead of staying frozen.
2. Put an **honest bound on the false-negative rate** of the suppressed flags
   (the panel suppresses ~1,176 of 3,450 surfaced today, and a much larger
   strong-anchor-blind population sits under no rule at all — see "populations").
3. Serve as the **false-positive-clear adjudicator** for single-anchor BDC
   CIK-quarters. Measured fact: v1 BDC FV is **single-anchor** on companyfacts
   almost everywhere — there is no independent cross-target anchor (CUSIP overlap
   with N-PORT is structurally zero: 0 of 574K BDC rows carry CUSIP; issuer-level
   cross-source is coupled to the paused entity-resolution track). So a human
   reading the source filing is the only available second opinion for the tail.

## Non-negotiables

- **Labels come from the cached source filing** (10-K/10-Q inline XBRL / HTML
  schedule of investments + financial statements under `data/raw/`), **never**
  from `private_markets_holdings.csv` or any pipeline output. Output-adjudicated
  labels measure nothing.
- **Firewalled / held out.** Gates and the fix-proposing agent must not tune
  against the gold set. A gold-found error may *motivate* a rule, but that rule's
  precision is then measured on a **fresh draw**, never the draw that inspired it.
- **Labeler is independent of the fixer.** The labeler is a constrained agent
  whose only job is read-source → emit label + citation, **blind to the pipeline
  output**. Independence axis = different inputs: the labeler consumes the raw
  filing; the fixer consumes the parsed output.
- **`ambiguous` / `indeterminate` is a first-class label.** Do not force a call on
  genuinely ambiguous source (rate scale, affiliation axis, lien when the filer
  gives no subtotal).

## Scope

- v1 cohort = the **77 wrapped BDCs** (`data/overrides/bdc_xbrl_wrappers/*.json`),
  **Q4 2022 onward**.
- Unit = **position-quarter**, rolled to **CIK-quarter**.

## Deliverables (stop for review — do not mass-label)

1. **Label schema** — versioned, append-only artifact.
   - Per-position: `true_fair_value`, `true_cost`, `true_classification`,
     `true_rate`, `true_maturity`, `true_lien`, `source_ref` (accession +
     `context_id`), `adjudicator`, `date`, `ambiguous`.
   - Per-CIK-quarter: `true_total_investments_fv`, `true_position_count`,
     subtotal/comparative row list.
   - Every label records the **pipeline version it was labeled against**.

2. **Review harness — build this FIRST (the force-multiplier).** Per sampled unit,
   show the cached source excerpt and the pipeline value **side-by-side** with the
   labeler agent's **candidate label pre-filled**, and let the human
   accept / reject / mark-ambiguous in seconds. This turns labeling from "go hunt
   for the filing" into "glance and click." For a one-person operation this tool
   is the difference between a gold set that accrues and one that never gets built.

3. **First stratified sample — drawn and stored, not yet labeled at scale.**
   - **Tail census** — every position / CIK-quarter above an FV threshold
     (bounded; highest dollar-coverage per label; human-labeled). One $3B position
     is worth more than a thousand $30M ones.
   - **PPS body sample** — probability-proportional-to-size, for a
     Horvitz–Thompson FV-weighted estimator.
   - **Three populations:**
     - **surfaced flags** → precision (the ~2,274 surfaced rows);
     - **suppressed flags** → recall / FN bound, oversampling the
       `row_warn_strong` packets and the strong-anchor-blind-cell suppressions;
     - **silent-bulk** → errors no rule fired on (the ~998 fund-quarters / 38.5%
       with no strong FV/cost anchor — `validation_coverage_gaps.csv`).

4. **Labeler protocol + calibration plan.** How the agent reads source and cites;
   the **human-audited fraction** that establishes the labeler's own error rate;
   and how that error **propagates into the published CI** ("calibrate the
   calibrator"). The labeler's error is part of the bound, not assumed zero.

5. **Estimators.** Per-stratum precision / recall with **Wilson CIs**. The CI will
   be **wide** (small solo sample) and must be **surfaced honestly on the
   frontend** ("confidence interval from a limited audit sample"), not narrowed by
   assertion. A wide honest bound beats a narrow fabricated one.

## What the human hand-labels vs. what the agent drafts

Hand-label only the high-leverage strata:
1. The **material-tail census** (bounded; biggest dollars per label).
2. **Consequential FP-clear sign-offs** — only the ones that flip a publication
   decision.
3. **Calibrating the labeler agent** (mostly a one-time cost that unlocks the bulk).

Everything else — body sample, silent-bulk sample, suppressed-strata recall check
— the agent drafts and the human **spot-audits**. Do not hand-label those.

## Realistic sequencing (one person)

Ship the deterministic floor now → build the review harness → accrue the tail
census + recall spot-check **quarter by quarter** → let measured precision widen
the registry over time. The gold set is a steady honesty layer you grow, not a
wall to climb before launch.

First quarter is heavy (schema + first tail census + first harness). Every quarter
after is light — the new quarter's tail, a few escalations, periodic re-calibration.

## Honest fallback (state it as a legitimate option, not a failure)

If even the light per-quarter cadence is unrealistic for a solo operator, the
honest v1 posture is to **stay on the deterministic floor indefinitely** and
publish **"preliminary, single-anchor, not independently audited"** rather than a
fabricated CI. That is a legitimate launch posture. (A floor-only v1 sketch can be
provided on request.)

## Constraints (AGENTS.md)

- **Read-only** on `data/output/` and `frontend/public/data/`.
- **No SEC network calls** — cached filings only.
- **DuckDB / vectorized** for any repo-scale step; no row-wise pandas on the big
  frames.
- **No ad-hoc inline Python** for diagnostics — named temp scripts with timeouts
  and row limits if unavoidable; kill the process when done.
- **Report what was and was not run.**

## Stop condition

Schema + harness + first sample drawn + labeler protocol — **for review**. Do not
begin large-scale labeling until the design is approved.
