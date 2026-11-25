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

## 5. Method and operating model (owner, 2026-11-25)

Agreed in session. This replaces "copy production's keyword lists" as the design; the keyword rules are used once,
to draft the dictionary and to compare with production.

### 5.1 Who does what

| Job | Who | Stored as |
|---|---|---|
| Find a fund's label pattern | An agent, once per fund and per format | A rule in the fund's wrapper copy |
| Apply the pattern | Code, every build | Nothing; recomputed |
| Give an instrument text or an industry label its class, lien, type, sector | An agent, once per distinct text | A dictionary entry |
| Split a label the pattern cannot | An agent, once per label | A stored split |

No model runs during a build. Every stored entry records its value, an example row as evidence, the model that
proposed it, what accepted it, and the date. The stores are plain data files in git, read by dbt as fixed inputs.

### 5.2 The work queue (not the ledger)

The build lists, in one table: each distinct text with no dictionary entry; each label the pattern failed on; per
fund and quarter, the share of labels the pattern parsed. Those fields stay empty, under a ceiling; nothing is
guessed. A queue item says "the pipeline lacks an input". It has no disposition: it closes when the entry is added.
The findings ledger is separate and comes after (slice 6): it holds doubts about published values.

### 5.3 Acceptance: checks, never the proposing agent

- Pattern and split: the pieces rebuild the original label; a number read from the label equals the tag where both
  exist; the parse share is above a bar on every quarter, including quarters the agent did not see. The bar is set
  after the T1 measurement.
- Dictionary: two agents label each text independently, from a closed list of values. Agreement, plus consistency
  with the row's tags (a "loan" with shares and no maturity is inconsistent), is accepted. Anything else goes to the
  owner, batched by reason.
- A wrong entry is wrong on every row with that text. The dictionary is audited in order of fair value carried.

### 5.4 Who runs the agents (owner, 2026-11-25)

For now: subagents run by the session's controller as orchestrator. Simple models are preferred (the smallest
model that passes the checks; never Fable). The Codex fleet and the SDK loop are not used for this. Revisit if the
volume outgrows a session.

### 5.5 One quarter

Parse the new filings; build; the queue lists the new texts; agents propose; checks accept or route to the owner;
accepted entries are committed; rebuild. The measure of success is the number of new entries a quarter needs.

## 6. First measurement: the size of the three stores (2026-11-25)

`scripts/text/q_t1_label_samples.sql`, `q_t1_store_sizes.sql`, on published rows both pipelines hold. The split used
is a crude candidate written only to size the work (strip the affiliation segment; instrument after the last pipe,
or between "Investment Type" and "Interest Rate", or after the last " - ", or a last comma segment naming an
instrument word). It was not checked against the pages or against production's names.

| Fund | Rows | Distinct labels | Labels with no instrument text | Distinct instrument texts |
|---|---:|---:|---:|---:|
| Ares | 19,771 | 4,926 | 90 | 213 |
| BCRED | 15,499 | 4,375 | 3,752 | 84 |
| Blue Owl | 9,719 | 2,790 | 57 | 69 |
| Apollo | 7,290 | 4,155 | 76 | 314 |
| HPS | 8,442 | 2,248 | 2,073 | 33 |

New in each of the last four quarters (not seen in any earlier quarter):

| Fund | New instrument texts | New labels |
|---|---|---|
| Ares | 15, 7, 16, 11 | 147, 275, 341, 1,431 |
| BCRED | 3, 4, 2, 1 | 154, 1,275, 181, 119 |
| Blue Owl | 4, 5, 3, 4 | 68, 882, 60, 390 |
| Apollo | 8, 65, 14, 20 | 332, 337, 620, 279 |
| HPS | 11, 4, 0, 2 | 132, 820, 90, 45 |

What it shows:

1. The dictionary is small and carries forward: about 713 instrument texts in all, and 0 to 20 new ones a quarter
   (Apollo 65 once).
2. Whole labels do not carry forward. A filer changes its label format and nearly every label is new that quarter
   (Ares 1,431 of 1,439 at 2026-06-30, from "Issuer, Instrument" to "Issuer | Instrument"; BCRED, Blue Owl and HPS
   at 2025-12-31). So a split stored by whole label is lost at a format change. Stored splits must be rare; the
   pattern does the work, and a fund has one pattern per format, dated.
3. BCRED and HPS labels mostly carry no instrument at all ("Abacus Holdco 2, Oy | Non-Affiliated Issuer"). Their
   class and lien come from the printed section heading, not the label. For those two funds the dictionary is keyed
   on headings, and T2 needs the printed sections.
4. Not measured: how many labels the pattern would split wrongly (the size of the stored-splits store). That needs
   a pattern per fund checked against tags and against production's names: the first task of T1.

### 6.1 Second measurement: a candidate pattern against production's names (2026-11-25)

`scripts/text/q_t1_pattern_fit.sql` (samples: `q_t1_label_vs_production.sql`). A pattern per fund written by hand
from samples: drop the affiliation segment and the trailing row number; split at the last pipe, at Apollo's
"Investment Type" marker or first instrument phrase, at the last " - " (BCRED, HPS) or the last comma (Ares, Blue
Owl) when the tail names an instrument word; else at the longest tail already seen as an instrument text for the
fund (the dictionary anchor). Compared with production's issuer and instrument as letters and digits only.

| Fund | Distinct labels | Both agree | Issuer differs | Instrument differs | Production corrected (issuer / instrument) |
|---|---:|---:|---:|---:|---|
| Ares | 4,926 | 4,845 | 42 | 41 | 79 / 34 |
| BCRED | 4,375 | 4,318 | 50 | 9 | 24 / 5 |
| Blue Owl | 2,790 | 2,730 | 202 | 25 | 14 / 46 |
| Apollo | 4,155 | 4,047 | 8 | 5 | 83 / 48 |
| HPS | 2,248 | 2,235 | 8 | 6 | 9 / 2 |
| Total | 18,494 | 18,175 (98.3%) | 310 | 86 | 209 / 135 |

"Differs" counts labels production did not correct. Read from the examples, they are four kinds:

1. Production relabels the row: 200 of Blue Owl's 202 are the wrapper's relabelled contexts (the 202 parked
   relabel corrections). Not a split problem; they close when relabels are applied before the split.
2. The candidate pattern is too crude: a count with thousands commas ("Warrant to purchase up to 1,088,780 units")
   split at the wrong comma; a short anchor ("LLC First lien senior secured loan"). Fixable in the pattern.
3. The filer's label is malformed: "Investment Type Investment Type", "Frist Lien", a pipe in the wrong place, a
   whole table row written into the label ("..., 0.0932, SOFR (M), 0.05, 45590, ..."). These are the real stored
   splits.
4. Production is wrong and the candidate right: "Cadence - Southwick, Inc." is one company; production splits it
   into issuer "Cadence" and instrument "Southwick, Inc.".

Size of the stored-splits store, on this evidence: the low hundreds across five funds and four years (kind 3,
plus the part of production's 344 corrected labels that are label problems). Small enough for the design.

Limits of this measurement:

- Apollo's issuer test is weak: it only checks that production's issuer ends the text before the instrument. The
  label is "Industry Brand Issuer ..." with no separators ("Aerospace & Defense Kaman Kaman Corp"). Where the
  industry ends and the brand ends is not measured, and it is where production holds 83 corrections. It is the
  hard part of T1. The printed page may print the three in separate cells; not checked.
- Agreement with production is not correctness (kind 4). Nothing was compared with a page.
- The pattern was written by hand in one pass, not proposed by an agent and not checked on unseen quarters.

## 7. Decisions before T1

Applied on the controller's recommendation under the owner's standing delegation (2026-11-25, "run the first
measurement once done"); the owner has not confirmed them one by one and may overturn any.

| # | Question | Recommendation | Cost if wrong |
|---|---|---|---|
| T-a | Production's LLM caches (industry lookup by label, GICS by company name, lien cache, unclassified cache): re-derive, or load as fixed inputs? | Load as fixed, named inputs for the comparison only; the dictionary of section 5 replaces them field by field as it is accepted. Count the rows each one decides. Do not call an LLM from dbt | The new pipeline still depends on files only the old one writes; a named debt like D21 |
| T-b | The majority vote across quarters (a row's class replaced by the commonest class of its issuer and instrument): reproduce it? | Reproduce it as its own model, last, so its effect is counted row by row; decide after seeing the count | If skipped: classes differ from production on an unknown number of rows. If kept: a row's class depends on other quarters |
| T-c | Keyword lists that match inside words ("common" in "Commonwealth") | Superseded by section 5: the dictionary replaces the keyword lists for class, lien and type. The keyword rules draft the dictionary once and are compared with production; every text where they differ from the accepted entry is listed | A text the dictionary lacks is empty until an entry is accepted |
| T-d | Order-dependent emptying (principal and lien emptied under a first class, not restored when the class changes; the 14 BCRED rows are this): copy or not? | Do not copy. Empty by the final class only. Differences are `old_wrong`, counted | Rows differ from production by design |
| T-e | Source labels production never updates (`basis_spread_source` and others) and `basis_spread_kind` (always "unresolved"): reproduce? | No. This layer already names the rule for each value; compare values only | None seen |
| T-f | "Floor rate n%" in a label read as the interest rate; a label rate read under the reading reviewed for the tag | Do not copy the floor rule; flag rows it touches. Keep the label-rate reading under a ceiling for owner review | A handful of Apollo rates differ |

## 8. What is not known yet

- Row counts per production step for these five funds (the code report read no data): how many rows each cache,
  vote, section rule and correction decides. First task of T1 and T2 is to measure them.
- Whether the filed layer holds footnote links (needed for T5).
- Whether production's page-reading file (the "field status" artifact) is current for every filing; this layer
  reads the page from the filed layer directly, so it does not depend on it, but the comparison does.
- Whether any of the five tag an investment-type member or a reference-rate concept.

## 9. First step after approval

A plan for T1 only, in the form of the earlier slice plans. Its first task: a label pattern per fund and format,
checked against the tags and against production's names, to measure how many labels need a stored split (section 6,
point 4) and to set the parse-share bar.
