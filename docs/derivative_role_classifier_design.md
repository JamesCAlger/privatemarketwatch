# `derivative_role` Classifier — Design

Status: **design / not built.** Grounded in the 2026-06-16 derivative investigation
(`data/output/data_investigation_results.md`). This document specifies how to label each
extracted derivative position as a **portfolio** position vs. a **financing/ALM hedge** of the
BDC's own borrowings, with calibrated confidence, so that:

- the holistic **analytics** (portfolio-by-instrument-type) can include *portfolio* derivatives
  and exclude the fund's own liability hedges, and
- the **position-level indices NEVER include any derivative** (already enforced:
  `position_matching.py` excludes `asset_class IN ('CASH','DERIVATIVE')`).

This is the analog of the cash work (2026-06-15): a new analytics-only bucket that must not
perturb the indices.

---

## 0. Why a *role* label is needed (not just an asset_class)

BDC derivative tagging is dominated by the fund hedging **its own debt**, not investment
exposure. Measured facts:

- 111/425 BDCs hold derivatives. Types by breadth: FX forwards (53 CIKs), interest-rate swaps
  (48), FX/currency-other (26), IR floors (<=12, contaminated — see §5), options (10),
  caps/collars (4), currency swaps (3), total return swaps (2), futures (1).
- Interest-rate derivatives are ~**85–90% financing hedges**: 60/131 IR-swap member names name
  the BDC's *own notes* by maturity year; **zero** name a portfolio borrower. Notional ≈ 0.42×
  own debt (~0.20× portfolio) — tracks debt, not the loan book. They live in the derivatives
  note (49 CIKs) not the schedule of investments (5 overlap CIKs, all artifacts on inspection).

So a single "Derivatives" bucket would be dominated by treasury hedges and misrepresent
investment exposure. The role label separates them.

`derivative_role ∈ {portfolio, financing_hedge, uncertain}` + `role_confidence` (0–1) +
`role_mechanism` (which signal decided) + `role_evidence` (the tag/value used).

**Decision (owner, 2026-06-16): classify and retain BOTH sides.** Every extracted derivative
row carries a `derivative_role`. We persist the `financing_hedge` (BDC-level) bucket as
first-class data — its net FV + notional are exported — *even though the current front-end only
consumes the `portfolio` bucket*. The classifier, not the donut, is the deliverable; the
BDC-level derivatives are kept for future use (ALM/leverage analytics, rate-type views).

---

## 1. Extraction precondition (separate from this classifier)

The classifier presumes derivatives are first extracted into rows with `asset_class='DERIVATIVE'`.
Key contracts from the investigation:

- Derivative contexts are dimensioned on `us-gaap:DerivativeInstrumentRiskAxis` and **lack an
  investment-identifier dimension** — which is exactly why the current extractor skips them.
  Extraction must opt them in via the derivative axis, not the investment-identifier axis.
- **Net FV is READ from standard us-gaap concepts** (corrected 2026-06-16; an earlier
  "no tagged net-FV concept" claim was a regex bug — `<[a-z0-9]+:` skipped the hyphen in
  `us-gaap`). Priority: `DerivativeFairValueOfDerivativeAsset − DerivativeFairValueOfDerivative
  Liability` (46–47 CIKs); fallback `DerivativeAssets − DerivativeLiabilities` (68–76 CIKs);
  **78/111 derivative CIKs (~70%) have one of these**. Last-resort only: derive
  `DerivativesGrossUnrealizedGain − …Loss` (just 3 CIKs; per-contract gross G/L is $0 at
  period-end for most IR filers, so deriving would wrongly yield zero — do NOT default to it).
- **Net FV by type (for role split):** ~72 CIKs tag the net-FV concept *on*
  `DerivativeInstrumentRiskAxis` (per-type) → net FV assignable directly to role. ~48 CIKs tag
  only an entity-level total → allocate to role by per-type **notional** share (notional IS
  well tagged per type), or assign the fund's single net to its dominant role; flag low-purity
  allocations as `uncertain`.
- **Notional ≠ FV.** Store notional in a separate column (`derivative_notional`). Notional must
  never touch `fair_value`, `pct_of_net_assets`, or any FV aggregate. (Column reserved; the
  `DERIVATIVE` exclusion is already wired in position matching.)
- **Do NOT use the concept name to decide portfolio-vs-hedge** (some filers tag own swaps as
  `InvestmentOwnedAtFairValue`). Use the issuer/portfolio-company dimension (see S3).

---

## 2. Signals (ranked by reliability, with machine-readability)

| ID | Signal | Implies | Reliability | Source |
|----|--------|---------|-------------|--------|
| S1 | ASC-815 designation: `DesignatedAsHedgingInstrumentMember` / FairValue/CashFlowHedging | financing_hedge | High | XBRL axis (25–32 CIKs) |
| S2 | Hedged-item / member names own debt (`...NotesMember`, `...FacilityMember`, `HedgedItemsMember`) | financing_hedge | High | member text (60/131 IR members) |
| S3 | Has issuer/portfolio-company dimension (borrower named) | **portfolio**; if only `DerivativeInstrumentRiskAxis` → not portfolio | High | XBRL dims |
| S4 | Notional-to-debt reconciliation: IR notional ≈ own borrowings | financing_hedge; contradiction → uncertain | Medium-High (gate) | `fund_financials.borrowings` |
| S5 | Instrument-type prior: IR swap/floor/cap → hedge; TRS → portfolio; FX forward → portfolio FX hedge; option/warrant → portfolio | base rate | Medium (prior) | type member |
| S6 | Footnote/label text ("hedge interest rate risk on the Notes" vs "economic hedge of investments") | either | Medium | text |

Caveat (S5 contamination): `InvestmentInterestRateFloorAxis` is a **loan attribute**, not a
floor derivative — exclude it from the IR-floor type before applying any prior.

---

## 3. Decision logic (Layer 1 deterministic → Layer 2 overrides → validation gate)

Priority order; first match wins, each emits role + base confidence:

```
1. S3: issuer/portfolio-company dimension present        -> portfolio          (conf 0.95)
2. S1: designated hedge (FairValue/CashFlow/Designated)  -> financing_hedge    (conf 0.97)
3. S2: member names own Notes/Facility/Borrowing/Debenture-> financing_hedge   (conf 0.95)
4. type == TotalReturnSwap                               -> portfolio          (conf 0.85)
5. type in {IR swap, IR floor(deriv), cap, collar, currency swap}
     AND S4 notional ties to debt (0.1<=ratio<=1.5)      -> financing_hedge    (conf 0.85)
   type in {...} AND S4 ratio > 1.5 (or no debt figure)  -> uncertain          (conf 0.50)
6. type in {FX forward, FX/currency}                     -> portfolio          (conf 0.70)
7. type in {option, warrant, future}                     -> portfolio          (conf 0.65)
8. else                                                  -> uncertain          (conf 0.40)
```

- **Layer 2 — per-CIK overrides** (`data/overrides/derivative_role/<cik>.json`, same audited
  schema as other overrides: mechanism, evidence, confidence, residual_risk, created_by,
  review_id). For the ~5–12 CIK residual and any filer whose tagging defeats Layer 1.
- **Validation gate (cannot be satisfied by editing output):** the S4 notional-to-debt
  reconciliation runs independently and flags positions whose Layer-1 role *contradicts* the
  notional evidence (e.g., labeled portfolio but notional ties to debt) → force `uncertain`,
  surface for review. This is the gate, not a feature input.

Everything below a confidence threshold (default 0.6) is `uncertain` and is **surfaced, never
silently bucketed**.

---

## 4. How the buckets consume the label

- **Indices:** exclude ALL derivatives regardless of role (`asset_class='DERIVATIVE'` already
  excluded in `position_matching.py`). Non-negotiable.
- **Data layer — both buckets persisted (decision 1):**
  `_export_portfolio_characteristics` emits, for the as-of quarter, BOTH
  `portfolioDerivativeFv` (net FV of `role='portfolio'`) and `financingHedgeFv` +
  `financingHedgeNotional` (net FV + notional of `role='financing_hedge'`). Mirrors the
  `cashFv` pattern. Both are written even though the front-end currently reads only the first.
- **Front-end (now):** the instrument donut adds a single **Portfolio Derivatives** slice from
  `portfolioDerivativeFv`. The BDC-level/financing-hedge figures are available in the JSON for a
  later ALM/leverage view; no donut slice yet.
- **`uncertain` (decision 4): routed to the universal shadow validator, not the front-end.**
  Uncertain rows (and notional-gate contradictions) are NOT shown as a UI slice. They are
  emitted to the validation-results ledger via a new shadow adapter (§4a) so they flow through
  the same agentic-review surfacing as every other review step. Their FV is excluded from the
  portfolio slice until a review resolves them.

## 4a. Shadow-validator integration for `uncertain` (decision 4)

The shadow validator (`scripts/shadow_adapter.py` + `scripts/shadow_validation_runner.py`)
normalizes every review source into one tier-tagged ledger and surfaces a scored subset for
agentic review. `derivative_role` joins it as a new engine — the same pattern as `source_recon`
and `row_validation`, which defer to their own confidence.

1. **Review artifact** (written by the role classifier): `data/output/derivative_role_review.csv`
   with one row per reviewable derivative position/group:
   `cik, report_date, mechanism, role_confidence, net_fv, notional, evidence`.
   `mechanism ∈ {derivative_role_uncertain, derivative_role_notional_contradiction}`
   (extend as new ambiguity modes are found). `role_confidence ∈ {high, medium, low}` band.

2. **Adapter** `_derivative_role_select()` in `shadow_adapter.py`, added to `adapter_selects()`,
   returning the 12-column ledger schema
   (`engine|rule_name|tier|enforcement|cik|period_kind|period|status|metric|metric_name|n_units|mechanism|src_confidence`):

   ```sql
   SELECT 'derivative_role' AS engine, mechanism AS rule_name,
          'tight' AS tier,              -- notional-to-debt is a reconciliation gate
          'advisory' AS enforcement,
          CAST(cik AS VARCHAR) AS cik, 'report_date' AS period_kind,
          CAST(report_date AS VARCHAR) AS period,
          'fail' AS status,
          round(sum(net_fv)/1e6, 2) AS metric, 'uncertain_deriv_fv_m' AS metric_name,
          count(*) AS n_units,
          mechanism AS mechanism, lower(role_confidence) AS src_confidence
   FROM read_csv_auto('.../derivative_role_review.csv', sample_size=-1)
   GROUP BY cik, report_date, mechanism, role_confidence
   ```

3. **Runner scoring** (`shadow_validation_runner.py` confidence CASE): add
   `WHEN l.engine='derivative_role' THEN 'derivative_role_' || COALESCE(l.src_confidence,'na')`,
   and add `derivative_role_high` / `derivative_role_medium` to the `surface` whitelist
   (`derivative_role_low` stays unsurfaced as noise, matching the source_recon grading).

This makes `uncertain` derivatives reviewable through the existing universal pipeline (mechanism +
confidence carried so the runner defers to the classifier's own grade), rather than a bespoke
one-off review path.

---

## 5. Calibration & honesty

- Estimate base rates P(role | type) from two label sources: (a) the designation-tagged subset
  (selection-biased — filers who formally designate differ), and (b) the notional-to-debt gate
  (unbiased across all 111 filers). Prefer (b) for calibration.
- Report **coverage**: share of derivative net FV assigned at high confidence vs. the
  `uncertain` residual. From the investigation the residual is small (~5–12 CIKs for IR).
- This is **epistemic** uncertainty (a definite-but-unobserved label), so it shrinks with
  evidence; a genuinely aleatory minority remains (TRS used as leverage vs. exposure; FX
  forwards hedging mixed asset+liability FX). Keep `role_confidence` visible.

---

## 6. Validation / tests (per AGENTS.md)

- Source reconciliation: notional-to-debt gate (§3) as a first-class artifact.
- False-positive tests: (a) a portfolio loan with an `InvestmentInterestRateFloorAxis` attribute
  is NOT classified as a derivative; (b) an own-`...2029NotesMember` swap → financing_hedge, not
  portfolio; (c) a TRS → portfolio.
- Notional-never-touches-FV test (max/sum sanity on derivative rows).
- Indices byte-identical gate (same isolation method used for cash): real index classes
  unchanged after derivatives are added.

---

## 7. Decisions

Resolved (owner, 2026-06-16):
1. **Scope** — classify and **retain both** `portfolio` and `financing_hedge` (BDC-level)
   buckets as first-class data; front-end consumes `portfolio` now, BDC-level kept for later
   (§0, §4).
4. **`uncertain` handling** — route to the **universal shadow validator** for agentic review
   (new `derivative_role` engine), not a UI slice; uncertain FV excluded from the portfolio
   slice until resolved (§4a).

Resolved (owner + evidence, 2026-06-16):
2. **Extraction depth** — **fund-level net-FV + notional first** (lower risk, fast, sufficient
   for the analytics figure and the role/notional gate); per-contract later if needed.
3. **Net-FV methodology** — **READ** us-gaap `DerivativeFairValueOfDerivativeAsset − …Liability`
   (fallback `DerivativeAssets − …Liabilities`), per-type where dimensioned (~72 CIKs) else
   entity-level allocated by notional (~48 CIKs); gross gain−loss is last-resort (3 CIKs). Set
   by the net-FV reliability spot-check (§1).

All four decisions resolved; design ready to build. Net-FV coverage ~70% of derivative CIKs at
fund level with a clean tagged anchor; the ~30% residual + low-purity allocations route to the
shadow validator (§4a).
