# Asset-Classification Audit & Amendment Plan (BDC holdings)

Date: 2026-06-28
Scope: BDC `asset_category` / `index_classification` / `asset_class` correctness.
Status: measured problem statement + phased plan. No code/data changed yet.
Method: read-only cross-reference audit over `data/output/private_markets_holdings.csv`
(574,828 BDC rows; current quarter = 2026-03-31) and `data/output/bdc_holdings.csv`
(1,180,533 raw rows). Diagnostic scripts were temporary and removed.

---

## TL;DR

1. The existing `validate_holdings.validate_classification()` only checks **internal
   consistency** (derived fields agree with `asset_category`). It treats `asset_category`
   itself as ground truth, so an upstream label error (Treasury bill -> LOAN) passes every
   rule. The missing layer is a **structure-vs-category** audit.
2. The deterministic structural lever the classifier is supposed to use -- the XBRL
   `investment_type` axis (`classification.py:_sql_classify_bdc_asset` Priority 0) -- is
   populated on **0.1% of rows**. The extractor drops it. This is the same filing-lineage
   gap that blocks the conservation look-through carvebacks
   (`data/output/agent_investigate/1975736/REVIEW_carveback.md`).
3. Only the **CASH** family is unambiguous error. Most LOAN/EQUITY/FUND "mismatches" are
   **fund-of-fund / JV look-through**, where the name carries the underlying instrument's
   label but the FUND classification may be correct. Keyword-patching those would inject
   errors.
4. The **credit-vs-equity fund axis** has a concrete, material bug: "LP interest" is treated
   as a private-equity signal, so **BCRED Emerald JV LP ($1.54B, the single largest position
   in the current-quarter PRIVATE_EQUITY_FUND bucket, ~54% of it) -- a credit JV held by
   Blackstone Private Credit Fund -- is labeled private equity.**

---

## 1. Measured problem

### 1a. Existing validation is consistency-only
`validate_classification()` (`pipeline/validate_holdings.py:624`) runs 9 cross-reference
rules. Each checks downstream agreement, e.g. "LOAN/DEBT + CORPORATE -> asset_class
PRIVATE_CREDIT" (`:617`). All take `asset_category` as truth. A Treasury bill mislabeled
`LOAN` is internally consistent and passes all 9. There is no check that `asset_category`
agrees with the filing's structure.

### 1b. Structure-vs-category mismatches (all BDC quarters; "current" = 2026-03-31)

| Family (structure of name/instrument != asset_category) | Rows | $FV | Current qtr | Dominant wrong labels |
|---|---|---|---|---|
| **CASH** (treasury bill, t-bill, MMF, repo, govt obligation) | 62 | **$5.27B** | 1 / ~$0 | LOAN 28/$3.43B; OTHER 8/$1.37B; FUND 26/$0.47B |
| **LOAN** (first/second lien, term loan, revolver) | 29 | $8.15B | 3 / $0.10B | FUND 10/$7.4B; EQUITY 15/$0.65B |
| **EQUITY** (common/preferred stock, warrant, units) | 205 | $0.94B | 36 / $0.05B | FUND 146/$0.67B; LOAN 46/$0.16B |
| **FUND** (feeder fund, LP interest) | 1,991 | $12.69B | 339 / $1.29B | EQUITY 1,641/$5.1B; LOAN 325/$7.5B |

Interpretation:
- **CASH is the real defect.** Literal cases: `"Cash Equivalents US Treasury Bill ... Maturity
  Dissolution Date 4/22/2025"` -> LOAN ($239M); `"U.S. Treasury Bills"` -> OTHER
  ($234M/$189M/$170M). Flat misclassifications.
- **LOAN/EQUITY/FUND mismatches are mostly look-through, NOT errors.** Largest "LOAN"
  mismatch is `"Related Party PSLF First Lien Secured Debt"` -> FUND ($1.27B): the BDC's
  interest in a JV/fund whose name carries the underlying instrument label. FUND is arguably
  correct. Same for `"Senior Loan Fund JV I, LLC ... Membership Interest"` and `"Middle Market
  Credit Fund, LLC, Subordinated Loan"`. These need filing lineage + adjudication, not a
  keyword.

### 1c. v1 harm framing (anti-sycophancy)
Cash is out of v1; the conservation `value_sum` excludes `asset_category='CASH'`. Any
cash-equivalent mislabeled LOAN/OTHER is therefore **not excluded** and leaks into the
published BDC fair value. Historically ~$5.3B sat under non-CASH labels, but **at the
current published quarter the leak is ~$0** by strong tokens. This is **not** a live multi-
billion hole in v1 today; it is an **unguarded, silently-regressible mechanism** with a large
historical footprint. The goal is to make the exclusion reliable and measured, not to chase a
currently-small number.

### 1d. Reverse direction is clean (cash precision is fine; recall is the issue)
429 rows labeled CASH ($16.1B); the 60 without a strong token are still genuinely cash
(`First American Treasury Obligations Fund`, `BlackRock Liquidity Funds T-Fund`), caught by
the guarded `treasury` keyword (`!=CORPORATE`). Low false-positive rate today.

---

## 2. What the extraction already provides (decisive)

The classifier's "Priority 0: XBRL investment_type axis" (`classification.py:420`) is the
intended deterministic signal. It is populated on **1,318 of 1,180,533 rows = 0.1%**.
0 of 195 CIKs have it on >=80% of rows; 194/195 have it on <5%. `bdc_dimensions_raw` carries
the axis on the same 0.1%.

Filers DO tag investment type in iXBRL (the 1,318 rows show clean members:
`seniorsecuredfirstliendebtmember`, `preferredstockmember`, `commonstockmember`,
`revolvermember`). The extractor isn't persisting it. Per the carveback
(`1975736/REVIEW_carveback.md:22-26`), `bdc_holdings` also exposes no SOI section label /
XBRL role / `source_row_id`.

Consequence: tier-(b) "derive asset_category from the filer's own type axis / SOI section" is
currently impossible at scale because the lineage that would feed it is dropped during
extraction. This is the same root-cause gap that blocks the conservation look-through
carvebacks. Fixing extraction-side capture is the highest-leverage move -- it unblocks both
classification and conservation.

---

## 3. Credit-vs-equity FUND axis bug (the Blackstone JV case)

### Confirmed in data
`BCRED Emerald JV LP` -- **$1,539.7M (current quarter)**, held by CIK 0001803498 =
**Blackstone Private Credit Fund (BCRED)** -- is classified `index_classification =
PRIVATE_EQUITY_FUND`, `asset_class = PRIVATE_EQUITY`. Sister vehicle `BCRED Verdelite JV LP`
($97M) same. These are credit JVs (they hold first-lien loans) held by a credit fund.

### Materiality
Current-quarter BDC FUND-exposure buckets: `PRIVATE_CREDIT_FUND` 77 rows/$4.48B vs
`PRIVATE_EQUITY_FUND` 259 rows/$2.83B. **BCRED Emerald alone is $1.54B = ~54% of the entire
PE-fund bucket.** Correcting it shifts the cohort fund-mix ~25% toward credit and roughly
halves reported fund-equity exposure. Feeds v1 instrument/exposure analytics (indices are out
of v1; the credit-vs-equity mix is not).

### Exact mechanism
`_sql_classify_index()` (`classification.py:524-527`) decides PC-fund vs PE-fund by counting
keyword hits in `_combined_fund_text = issuer_name + instrument_description`. For this row =
`"bcred emerald jv lp" + "lp interest"`:
- Credit signals = 0: `_CREDIT_FUND_SIGNALS` (`:169`) looks for `credit`/`lending`/`loan`/
  `debt`/`senior`; `contains('bcred','credit')` is **false**. The fund's credit identity is
  invisible.
- PE signals = 1: `_PE_FUND_SIGNALS` (`:176`) includes `"lp interest"` / `"partnership
  interest"`. Instrument "LP Interest" matches -> `has_pe=True, has_credit=False` ->
  `PRIVATE_EQUITY_FUND`.

Root bug: **"LP interest" is a legal-form token, not an asset-class signal.** Credit JVs, PE
co-invests, and RE partnerships all use LP interests. The same list also drags genuine credit
vehicles into PE (e.g. `MS Private Loan Fund I/II, LP`).

This is the same look-through disease, one axis over: the real answer lives in the holder's
strategy and the JV's look-through holdings, neither of which the name-keyword classifier
sees.

---

## 4. Phased amendment plan

Tiers per AGENTS.md: high-precision deterministic rules with guards (a); derive from captured
structure (b); agentic review on residuals as per-CIK audited config (c). Per-CIK corrections
as audited config, NOT global keyword growth.

**Phase 0 -- Make it measurable (do first; no behavior change).**
Promote the structure-vs-category audit to a first-class `validate_holdings` function (e.g.
`validate_classification_structure()`), emitting a per-family / per-CIK artifact split into
error-grade (CASH) vs look-through-grade (LOAN/EQUITY/FUND). Add a fund-axis check: flag every
PRIVATE_EQUITY_FUND / PRIVATE_CREDIT_FUND row whose ONLY signal is a legal-form token, ranked
by $FV. This is the baseline every later phase is graded against and the gate that makes the
cash exclusion measured.

**Phase 1 -- Tier (a): high-precision guarded deterministic rules (small, tested).**
- Cash: reclassify to `asset_category='CASH'` on strong multi-word tokens (`treasury bill`,
  `t-bill`, `treasury obligations fund`, `government obligations fund`, `money market`,
  `repurchase agreement`, `commercial paper`, `u.s. treasury`), keeping the `treasury`-as-
  `!=CORPORATE` guard. Borrower guards: never fire on an operating company whose name merely
  contains "treasury"/"sweep" with a corporate suffix.
- Fund axis: demote `lp interest` / `partnership interest` / `membership interest` out of
  `_PE_FUND_SIGNALS` so they stop FORCING PE. Honest caveat: this alone makes BCRED Emerald
  fall to UNCLASSIFIED (not credit), and genuine bare PE co-invests (`CD&R Value Building
  Partners`, `Percheron Horsepower dba Big Brand Tire`) also drop to UNCLASSIFIED. Necessary
  (stops a wrong confident label) but not sufficient -- must pair with Phase 2.
- One false-positive test per new rule (`Apex Group Treasury LLC`, a `... Sweep Inc.`
  borrower, `Total Safety Holdings`; a real PE co-invest must not become credit; a real credit
  JV must not stay PE).

**Phase 2 -- Tier (b): capture/use structure; fund-strategy prior (highest leverage).**
- Extractor: populate `investment_type` from the iXBRL type-axis member for all rows (it is in
  the contexts; only 0.1% kept today) and carry the SOI section label from the HTML bridge onto
  `bdc_holdings`. Then `_sql_classify_bdc_asset` Priority 0 actually fires. Measure by axis
  fill-rate before/after and Phase-0 mismatch reduction. Overlaps the lineage work the
  carveback escalations request.
- Fund-strategy prior (machinery already exists): the holder's strategy is a strong source-
  grounded prior -- a JV held by a private-credit BDC is overwhelmingly a credit JV. The repo
  already has `_apply_fund_strategy_asset_class_override()` (`unified_holdings.py:1413`) doing
  exactly this for REAL_ESTATE funds from a strategy reference file. Extend that pattern: for
  FUND-exposure rows, let the holder CIK's N-CEN/prospectus strategy (BCRED = credit) set
  `asset_class`/`index_classification` of its fund/JV interests when the row signal is absent or
  weak. This is the AGENTS.md Layer-3 gate and cleanly fixes BCRED Emerald.

**Phase 3 -- Tier (c): agentic look-through adjudication (per-CIK audited config).**
For look-through residuals (JV / fund-of-fund / structured-finance), run the B-fleet per-
instrument pattern with the full filing SOI as evidence (the shared cached-filing search
primitive). Emit per-CIK audited `asset_category` / `index_classification` / `asset_class`
overrides (mechanism, evidence citation, confidence, before/after FV) under
`data/overrides/...`, NOT global keywords. Depends on Phase 2 lineage.

**Phase 4 -- Verify every change.** `validate_classification` (consistency) + the new structure
audit (Phase 0) + targeted classification tests + a false-positive test per new rule, then
`--unified` rebuild and `scripts/diff_outputs.py --semantic`. Report FV moved per family and
confirm cohort / current-quarter conservation still reconciles.

### Recommended sequence
0 -> 1 -> 2 -> 3. Phase 0+1 are low-risk and harden the v1 cash exclusion and the fund-axis
label. Phase 2 is the leverage point (also unblocks conservation). Phase 3 is the only piece
needing agents and depends on Phase 2. Do NOT start at "fix the $12.7B FUND family / $2.8B PE
bucket by keyword" -- most of the FUND family is correct look-through labeling, and the PE-fund
fix needs the holder-strategy prior, not deleted keywords.

---

## 5. Open follow-ups (not yet done)
- Pull the full list of FUND rows whose only signal is a legal-form token (complete blast
  radius of the LP-interest bug).
- Check the N-CEN / strategy reference file to confirm BCRED's strategy is captured for the
  Phase-2 override, and what fraction of FUND-holding CIKs have a usable strategy signal.
- Decide whether to land Phase 0 (the structure audit) as a real validation function now.
