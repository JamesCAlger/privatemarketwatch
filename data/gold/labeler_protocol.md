# Labeler protocol + calibration + estimators (gold set, v1 BDC cohort)

This is the operating manual for turning the frozen sample frame
(`samples/sample_frame_*.jsonl`) into measured precision / recall / FV-error with
honest confidence intervals. It defines three roles, how the labeler reads and
cites source, how we measure the labeler's OWN error rate and fold it into the
published CI, and the estimators.

## Roles (the independence firewall)

| Role | Input it may read | Output | Must NOT see |
|---|---|---|---|
| **Labeler agent** | the raw cached filing ONLY (`data/raw/filings/bdc_html/...`) | candidate label + citation -> `candidates/candidates_<draw>.jsonl` | `private_markets_holdings.csv` or any pipeline artifact |
| **Human adjudicator** | source + pipeline value + agent candidate (in the harness) | confirmed label -> `labels/*.jsonl` | — (final authority) |
| **Fixer agent** (separate track) | pipeline output, the ledger | proposed parse/config rule | `labels/*.jsonl` (held out) |

The independence axis is **different inputs**: the labeler reads the filing; the
fixer reads the parsed output. A label is never copied from the pipeline; the
pipeline value is shown to the human only so they can see whether it matches source.

## Labeler reading protocol (per field)

Read the schedule of investments and the financial statements in the cached
filing. For each field, record the value AND a citation; if the source is
genuinely indeterminate, mark the field `ambiguous` (do **not** force a value).

- **true_fair_value / true_cost** (per position): read the position's row in the
  schedule; take the Fair Value and Cost columns for the *specific tranche* that
  matches the identifier. Record the **dollar unit** from the table header
  (thousands / millions) — unit ambiguity is the most common silent error. Cite
  the iXBRL `contextRef` of the FV fact when present (strongest, per-position
  exact); else cite table + row text + quoted value.
- **true_total_investments_fv** (per CIK-quarter): read the **statement line**
  "Total investments, at fair value" (balance sheet) or the schedule grand total —
  NOT the sum of extracted rows. This is the independent anchor; cite the line.
- **true_position_count** (per CIK-quarter): count genuine position rows; exclude
  subtotal/category rows and prior-period (comparative) rows. List the
  subtotal/comparative identifiers in `subtotal_rows` / `comparative_rows`.
- **true_classification**: from the instrument description — term loan / revolver /
  delayed draw -> DIRECT_LENDING; equity / warrant / preferred -> DIRECT_EQUITY;
  fund/partnership interest -> a *_FUND class. `ambiguous` if the filing names no
  instrument type.
- **true_lien**: from the filer's own lien subtotal / section header or the
  instrument name (First Lien / Second Lien / Unsecured / Subordinated).
  `ambiguous` (left null) if the filing gives no lien evidence — **never default to
  First Lien**.

**Ambiguous triggers (first-class, not failures):** rate scale unclear
(decimal vs percent), affiliation-axis double-listing, subtotal-vs-position
uncertainty, dollar-unit unclear, cross-period (comparative) row indistinct.

## Flag adjudication (surfaced / suppressed strata)

The unit is a panel flag `(engine, rule_name, cik, period, metric)`. Read the
source and decide whether the flagged condition is a **real defect at source**:
`real_error` / `false_alarm` / `ambiguous`, with a one-line citation.
- surfaced flags -> **precision** of the rule (real_error / decided).
- suppressed flags -> **false-negative rate** of the suppression (real_error among
  suppressed) — the honest bound on the ~36,000 surface=`false` flags.

## Sampling framing (what each stratum targets)

- **tail_census + pps_body** are drawn from the **as-of snapshot** = each fund's
  latest filing on/before the `--as-of` date (default **2025-12-31 / Q4 2025**;
  cohort snapshot ~$400B, 75 funds, 33,211 positions = the published as-of cohort
  AUM). The FV-weighted error estimate therefore targets the numbers the frontend
  shows, not a multi-quarter cumulative base or the bleeding edge. Tail K=200 covers
  ~19.7% of snapshot FV exactly (min position ~$208M, all distinct instruments);
  the body samples the remainder.
- **silent_bulk** is **all-history** on purpose: the strong-anchor blind spots skew
  to OLD quarters (recent quarters are well-anchored), so the "errors no rule
  caught" question lives there, not in the snapshot.
- **surfaced_flag / suppressed_flag** are all-history (rule precision/recall over
  the full panel output).

## Division of labor (solo-operator)

- **Human hand-labels:** the tail census (200 positions + 25 CIK-quarters) and any
  consequential FP-clear sign-off. These carry labeler-error ~ 0. (Once the labeler
  agent is wired, it pre-fills candidates for the tail too, so the human confirms
  rather than transcribes.)
- **Labeler agent drafts, human spot-audits:** PPS body, silent-bulk, surfaced and
  suppressed flags. The human fully re-adjudicates a random **audit fraction
  f = 0.2** of each agent-drafted stratum (blind to the agent's answer first).

## Calibrating the calibrator

The labeler agent has its own error rate; we measure it instead of assuming zero.

1. On the audited fraction f, compare human (truth) vs agent for each unit. Count
   agent false-positives (agent flags error where human says none) and agent
   false-negatives (agent misses a human-confirmed error). Estimate `e_FP`, `e_FN`
   each with a Wilson CI.
2. **Point correction.** For an agent-drafted stratum with raw agent error rate
   `r_agent`, the bias-corrected true error rate is
   `r = (r_agent - e_FP) / (1 - e_FP - e_FN)` (Rogan-Gladen), clamped to [0,1].
3. **CI widening.** The published interval convolves the sampling CI with the
   labeler-calibration CI (sum of variances on the logit/linear scale, conservative).
   A stratum measured purely by agent labels therefore reports a WIDER interval
   than its sample size alone implies — that width is honest, not a defect.
4. Human-labeled strata (tail) set `e_FP = e_FN = 0`.

## Estimators (implemented in `scripts/gold/estimate_gold.py`)

- **Precision (surfaced):** `p = real / (real + false_alarm)`; `ambiguous`
  excluded from the denominator but reported, plus a worst-case row treating all
  ambiguous as false_alarm. **Wilson 95% CI**.
- **FN / recall bound (suppressed):** real-error rate per confidence class
  (oversampled), aggregated across classes weighted by each class's ledger
  population. Wilson CI per class; stratified combination for the aggregate.
- **FV error (tail + body):** dollar-weighted. Tail is exact (`pi = 1`). Body is
  **Horvitz-Thompson**: `error_$ = sum_i err_i / pi_i`, `pi_i = min(1, n*size_i/total)`.
  Combine tail (exact) + body (HT) -> cohort FV-error as a % of cohort FV with the
  HT variance CI.
- **Silent-bulk error rate:** SRS within no-strong-anchor positions, `pi = n/N`;
  error rate with Wilson CI — the "errors no rule caught" rate in the blind region.

**Honesty rules.** Every published number carries its interval; never a point
alone. n is in the tens, so intervals are wide — surface them on the frontend as
"confidence interval from a limited audit sample". Report `ambiguous` counts
beside every estimate. A rule motivated by a gold-found error is measured on a
**fresh draw** (batch2+, different seed salt), never on the draw that surfaced it.

## Cadence

- First quarter (now): schema + harness + batch1 frame (done) -> label the tail
  census + a first audited slice of suppressed flags -> first precision + FN bound.
- Each later quarter: new-quarter tail, a few escalations, periodic re-calibration.
- Fallback: if even the light cadence is unsustainable, stay on the deterministic
  floor and publish "preliminary, single-anchor, not independently audited" — a
  legitimate posture, not a failure.
