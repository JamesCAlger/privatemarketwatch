# Text fields: spec (DRAFT for owner review, 2026-11-25)

Status: draft, not approved, nothing built. Branch `warehouse-text-spec`, cut from `warehouse-slice5` (owner, 2026-11-25).
Second spec of the intermediate layer (D2 of `warehouse/docs/intermediate_spine.md`: "fields read from text are a
second spec"). It comes before slice 6 (owner, 2026-11-25): findings need these fields.

Sources: `text_fields_production_trace_2026-11-25.md` beside this file (how production derives each field, read from code only) and the
measurements (queries `warehouse/scripts/slice5/q_text_*.sql`), on the 60,737 published rows
both pipelines hold for the five funds.

Agreement with production is not correctness. Production's text code is the least checked part of the old pipeline:
25 fragile points are listed in the code report, section 6.

## 1. Purpose

Hold, for every position, the fields that are not a tagged number: who the issuer is, what the instrument is, its
class, lien, rate type, reference rate, industry. With them:

- the 2,541 parked corrections (`deferred|field_not_held`) can be applied;
- the 1,772 unread rates can be read (406 need the row class and the printed rate type, 54 an Apollo label rule);
- the unit-count principals of D17 (166) can be emptied by class;
- slice 6 can raise findings that need a class ("a loan with no rate").

## 2. What production does, in one page

Three kinds of input, in this order:

1. **The row label** (the investment identifier member). Split into issuer and instrument. Generic rule for BCRED,
   Blue Owl, HPS; a wrapper regex for Ares and Apollo. Apollo's label also carries rate, PIK, spread, reference rate
   and maturity as text.
2. **Keywords** on issuer + instrument text: row class, index class, lien, instrument type. Global lists, plain
   substring matches.
3. **The printed page**: the column beside the tagged value (reference rate, "N/A" means fixed coupon), the section
   heading above the row (lien, industry, BCRED structured credit).

Then caches and votes: an LLM industry lookup by label, an LLM GICS label by company name, a lien cache, an
"unclassified" review cache, and a majority vote across quarters that overwrites a row's class with the commonest
class of the same issuer and instrument.

Measured on published rows:

| Field | Filled | Main source |
|---|---|---|
| issuer_name | 100% | label; 402 rows corrected |
| asset_category | 100% | keywords; LOAN 86% |
| index_classification | 100% | keywords, vote, sections, caches; 30 corrected |
| lien_position | 71 to 97% | keywords, then section heading |
| coupon_type | 68 to 97% | tags, label words, printed "N/A" |
| reference_rate_type | 63 to 92% | printed column (Ares, BCRED, Blue Owl, HPS); label text (Apollo, 6,179 rows) |
| extracted_industry | 80 to 100% | section heading, LLM lookup; 328 corrected (HPS 227, Apollo 101) |
| instrument_type | 0 to 80% | keywords; patchy |

## 3. Design rules (carried from the spine spec)

- One decision per model. Every value names its rule. Nothing is erased: the label as filed stays beside each
  parsed field.
- Fund-specific rules live in the fund's wrapper copy; global rules in seeds. No fund name in a model.
- A field no rule can decide is left empty with a reason, counted under a ceiling.
- Each slice ends with a build, a comparison with production per field, a cause for every group of differences,
  and a baseline entry.
- Production's known errors are not copied silently. Where this layer differs on purpose, the difference is
  `old_wrong` with its rows counted.

## 4. Slices, in dependency order

The class depends on the names, so names come first (this corrects the order given in session).

| Slice | Builds | Inputs already loaded | Unlocks |
|---|---|---|---|
| T1 | The label: affiliation strip, issuer, instrument (generic parser; Ares and Apollo regexes; per-fund strips) | identifier label (`int_context_feature`), wrapper copies | 613 name and instrument corrections; position text for every later slice |
| T2 | Row class (`asset_category`, `issuer_category`), index class, exposure, asset class, lien, instrument type; principal emptied by class | T1, the tagged numbers | D17 (166 principals); the loan test for PIK-only rows; class corrections |
| T3 | Printed-page rate fields: reference rate, fixed or floating, "N/A means fixed coupon", spread adjustments, Apollo label rates and maturity; then the PIK-only and margin readings | T2, printed rows and placements (filed layer) | the 1,772 unread rates; 1,044 rate-text corrections |
| T4 | Industry: section heading, Apollo label rule, GICS mapping | T1, printed rows | 328 industry corrections |
| T5 | Non-accrual flags (footnotes, dimension) | filed footnotes (check whether the filed layer holds them) | credit-stress measures |

Not in this spec: position matching and ids (D3, D9), entity resolution, `is_subsidiary` and the published basis
(built in slice 2).

## 5. Owner decisions needed before T1

| # | Question | Recommendation | Cost if wrong |
|---|---|---|---|
| T-a | LLM caches (industry lookup by label, GICS by company name, lien cache, unclassified cache): re-derive, or load as fixed inputs? | Load as fixed, named inputs, like position ids (D3). Count the rows each one decides. Do not call an LLM from dbt | The new pipeline still depends on files only the old one writes; a named debt like D21 |
| T-b | The majority vote across quarters (a row's class replaced by the commonest class of its issuer and instrument): reproduce it? | Reproduce it as its own model, last, so its effect is counted row by row; decide after seeing the count | If skipped: classes differ from production on an unknown number of rows. If kept: a row's class depends on other quarters |
| T-c | Keyword lists that match inside words ("common" in "Commonwealth"): copy as they are, or fix? | Copy first (reproduction), list every row where a whole-word match would differ, then decide per list | Copying keeps known misreads for one slice |
| T-d | Order-dependent emptying (principal and lien emptied under a first class, not restored when the class changes; the 14 BCRED rows are this): copy or not? | Do not copy. Empty by the final class only. Differences are `old_wrong`, counted | Rows differ from production by design |
| T-e | Source labels production never updates (`basis_spread_source` and others) and `basis_spread_kind` (always "unresolved"): reproduce? | No. This layer already names the rule for each value; compare values only | None seen |
| T-f | "Floor rate n%" in a label read as the interest rate; a label rate read under the reading reviewed for the tag | Do not copy the floor rule; flag rows it touches. Keep the label-rate reading under a ceiling for owner review | A handful of Apollo rates differ |

## 6. What is not known yet

- Row counts per production step for these five funds (the code report read no data): how many rows each cache,
  vote, section rule and correction decides. First task of T1 and T2 is to measure them.
- Whether the filed layer holds footnote links (needed for T5).
- Whether production's page-reading file (the "field status" artifact) is current for every filing; this layer
  reads the page from the filed layer directly, so it does not depend on it, but the comparison does.
- Whether any of the five tag an investment-type member or a reference-rate concept.

## 7. First step after approval

A plan for T1 only, in the form of the earlier slice plans, with its own measurements and owner questions.
