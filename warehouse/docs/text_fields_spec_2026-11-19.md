# Reading text into fields: spec

Status: DRAFT written 2026-11-19 from the owner's discussion of that day. Nothing here is built.
Companion to `intermediate_spine.md` (the spine reads tagged values; this reads printed and label
text). It is written as its own piece of work: it can be reviewed and scheduled apart from the
dbt slices, and it starts only after the spine reproduces production.

Nothing in this spec shows that a value read from text is correct. It describes a way to read text
that is repeatable, traceable to a rule, and loud when it cannot read something.

## 1. Purpose

Some fields are not tagged, or are tagged by some funds and printed by others: the reference rate,
the spread, floors, the industry, the issuer name, instrument wording, footnote status. Today they
are read by five separate mechanisms and by row-by-row fixes that do not carry forward (section 9).

The aim is one reusable method that turns text into fields through rules:

- a rule is written once per recurring shape of text, per fund, and carries forward every quarter;
- the rule is applied by code with no model involved;
- text no rule covers is left empty, counted and listed, never guessed;
- a filer changing its format is noticed before the build, not after.

## 2. What the owner has decided (2026-11-19)

| # | Decision |
|---|---|
| T1 | The method is the one Agent A already uses, generalised: group text into recurring shapes, give a bounded sample to an agent, the agent writes a rule and not row-by-row answers, code applies the rule. It is to be reusable wherever text must be read, headers and strings alike. |
| T2 | The model runs during the quarter-end pass, before the dbt build. The build itself never calls a model. |
| T3 | Rules live in the fund's wrapper, the one place for fund-specific rules (`warehouse/wrappers/<cik>.json`). No fund-specific logic in the general pipeline. |
| T4 | Bundles come first: the agent is given the text and its context, prepared by a query. The full document is the fallback. |
| T5 | Whether Jev is used is not decided. It needs more testing before any decision on its use is final. The one comparison so far, on 204 items, favoured a general agent (section 10); that agent was run once, and Jev was not tested in the role where its numeric score matters most, as a check. Until then a general agent is the working assumption for writing rules. |
| T6 | How a proposed rule is checked and accepted (the gate) is parked. It is the main open design question (section 11). |
| T7 | Compare like for like before improving: the rules the wrappers already hold are applied through the new mechanism and measured against production before any agent writes a new rule. |

Added later on 2026-11-19:

| # | Decision |
|---|---|
| T8 | The gate is set up extraction by extraction, or classification by classification. There is no single gate for all uses; each use gets its own check when that use is taken on (section 11). |
| T9 | The model pass starts with a fleet of Sonnet sub-agents, on usage credits or the subscription. Haiku is to be tested as well. |
| T10 | Agent A's existing grammar and anchor files are tested for whether they are useful. If they are, they are folded in (into the wrappers, through this method). If not, the work is redone under this method. |
| T12 | One model round per pass. Units that depend on each other (a column and the text shapes in it; a heading level and its labels) are decided together in one bundle. Detection is re-run after acceptance only as a check. |
| T13 | When a structural change in a fund's text is still uncovered at the build of record, that fund's build stops by default. The other funds build. Publishing with the field empty and flagged is the owner's recorded choice, made by raising that ceiling. A new name in a known slot never stops a build (section 4.1a). |
| T11 | The existing row corrections (3,911 for the five funds, most on text fields) are used as a test set for rules read from text. It is an imperfect one: each was typed by an agent reading a printed line, and some may be wrong. |

Decisions of the spine that apply here unchanged: a field that cannot be decided is left empty,
flagged and counted against a ceiling that fails the build if it grows (D5); where a field is both
tagged and printed the tag wins and the difference is recorded, and a field the filer never tags is
read from print by a fund rule (D6).

## 3. Where text has to be read

| # | Text | Where it sits | What it yields |
|---|---|---|---|
| 1 | Position label | In the tag | Issuer, instrument, sometimes rate, maturity, industry |
| 2 | Column headers | Printed page | Which field each column holds |
| 3 | Heading rows above positions | Printed page | Industry, instrument-type section, affiliation, issuer group |
| 4 | Subtotal, total and cash labels | Tag and page | Row role (already built in the spine, as general patterns) |
| 5 | Rate and spread cells | Printed page | Reference rate, spread, floor, cash and PIK parts |
| 6 | Reference-rate codes | Printed page | "S" means SOFR; "C" means CORRA from a date |
| 7 | Dates and amounts written as text | Printed page | Maturity such as "11/2026"; amounts with a currency |
| 8 | Footnote markers and footnote text | Printed page | Non-accrual, restricted, PIK, unfunded, non-qualifying |
| 9 | Table titles and captions | Printed page | Which table is the schedule, its date, whose it is, "continued" |
| 10 | Member names on other axes | In the tag | Which JV or entity a row belongs to (already built in the spine) |
| 11 | Scale and unit statements | Printed page | "in thousands", currency notes |

Out of scope: fund-level text (strategy language, fund highlights).

The eleven fall into three kinds of job:

| Kind | Question | Places | Form of the rule |
|---|---|---|---|
| Classify a slot | What is this column, heading, marker or table? | 2, 3, 4, 8, 9, 10 | "this header means this field" |
| Parse a string | Which parts of this text are which fields? | 1, 5, 7 | A pattern with named parts |
| Map a vocabulary | What does this code or label stand for? | 6, and the label lists in 3 and 8 | A lookup row |

All three forms fit the rule table of the spine (`intermediate_spine.md` section 5).

## 4. The method

The same six steps for every place in section 3.

| Step | What | Who |
|---|---|---|
| 1 Group | Text is grouped into recurring shapes. Each shape gets a signature | Code |
| 2 Match | Each shape is matched to the fund's rules: covered, not covered, or changed | Code |
| 3 Bundle | For each shape not covered or changed: a bounded sample with its context | Code |
| 4 Propose | An agent reads the bundle and writes a rule, or answers "cannot tell" | Agent |
| 5 Accept | The proposed rule is checked and accepted, or sent to the owner | Parked (section 11) |
| 6 Apply | Accepted rules are in the wrapper. Code applies them to every row | Code |

Rules of the method:

1. The agent writes rules. It never classifies or parses row by row.
2. The agent sees a bundle, not the filing. The full filing is a fallback when it answers "cannot
   tell", and that fallback is counted.
3. "Cannot tell" is a first-class answer. So is "no rule fits": the field stays empty.
4. A rule selects on features of the text and its position on the page. Never on a row or context id.
5. A rule is never edited. It is ended and a new one written (as in the spine).
6. Every value read from text names the rule that read it.

### 4.1 The unit: what one bundle is about

One bundle per thing that gets one rule.

| Unit | Roughly how many |
|---|---|
| A column of the schedule | About 10 per filing |
| A heading row | Tens to hundreds per filing |
| A text shape within a column | A handful per column |
| A footnote marker | Tens per filing |
| A label shape (Agent A's unit today) | A few to a few dozen per fund |

A row is not a unit. A rule about one row is a correction, and corrections do not carry forward.

Units that depend on each other travel in one bundle. The reading of a text shape depends on what
its column holds ("N%" in a rate column is not "N%" in a share-of-net-assets column), so a column's
bundle carries the shapes found in it, and the agent proposes the column's rule and its shapes'
rules together. The same holds for a heading level and the labels at that level. This is why the
pass needs one model round, not several (owner's question, 2026-11-19): nothing new appears after
the first detection; a dependent unit is simply decided with its parent. Shape rules are accepted
only if their column's rule is.

### 4.1a Heading rules are about structure, not names

| What is new in a filing | Example | New rule needed? |
|---|---|---|
| A new name in a known slot | The fund starts using "Financial Services" as an industry | No. The rule says "headings at this level are industries"; a new name is a new value |
| A new kind or level of heading | A geography level above industry; a second line under each industry | Yes. The page's structure changed |
| A heading that could be two things | A heading that might be an industry or an issuer name | Yes, for that heading |

- A heading rule is structural wherever the page allows it: it names a level, not a list of labels.
- A list of names is the fallback for a fund whose page does not separate the levels. Apollo is the
  case seen: about 500 distinct headings, industries and issuer names mixed, and its wrapper lists
  its industry labels for that reason. For such a fund a brand-new heading is undecided until it is
  classified.
- A new name in a known slot is listed for information and never blocks a build. What it does need
  is its mapping to a sector, which is a separate existing step: until mapped, the fund's own label
  is published and the sector is empty.

### 4.2 The trigger: which units need a decision

Most units repeat every quarter. A bundle is made only when a unit's signature is:

- **new**: no rule of the fund covers it; or
- **changed**: a rule covers it, but what sits under it has shifted (for example a column a rule
  reads as an all-in rate now holds mostly "S+N" text).

Everything else reuses the existing rule with no agent. "Changed" is how a filer's change of format
is flagged.

### 4.3 The bundle: what goes in

Everything a person would look at on the page to decide, and nothing derived from the old
pipeline's output.

| Unit | In the bundle |
|---|---|
| Column | Header cell, the whole header row, the most frequent cells below, the tags on those cells, the table's title |
| Heading | The heading, the headings before and after it, the next few rows, whether it appeared in earlier filings |
| Text shape | The shape, real examples, the column header, the other rate cells and tags on the same rows |
| Footnote marker | The marker and the footnote's text |
| Label shape | About 12 sample labels of the shape, the tagged fields of those rows, the labels that fit no shape |

- Tags go in. They are the best evidence where they exist.
- Size is capped by a fixed rule (most frequent first, a stated limit), so one filing always gives
  the same bundle. The cap is recorded.
- A bundle is built from the filed layer, which stores the page as filed. This removes a known
  fault of the old bundles, which were built from the extractor's output and inherited its mistakes
  (recorded 2026-06-16 and 2026-07-24).

## 5. Where it runs: the quarter-end pass

| Step | What happens | Model? |
|---|---|---|
| 1 | New filings are parsed into the filed layer | No |
| 2 | Detection build: dbt builds only the page structure, the units and the match against current rules. Output is the worklist | No |
| 3 | Model pass: the agent reads the worklist and proposes rules | Yes |
| 4 | Acceptance (section 11); accepted rules are written to the fund's wrapper | Parked |
| 5 | The wrapper change is committed. Detection is run once more as a check that the worklist is now empty or under its ceiling; this is the same code as step 2 and calls no model | No |
| 6 | Build of record: the full dbt build | No |
| 7 | Anything still not covered is empty, counted against its ceiling and listed | No |

- The build of record reads the wrappers as committed. Run again later, it gives the same data,
  with or without an agent available.
- The model's whole effect for a quarter is a diff to the wrappers, readable before the build.
- If the model pass is skipped the build still runs; new text is empty and listed.
- The first time a fund goes through, the worklist is everything. After that it is the few new or
  changed units.

## 6. What has to be built

In order. Items 1 to 3 need no agent.

| # | Piece | What it is |
|---|---|---|
| 1 | Page structure | Which table is the schedule, which row is the header, which column each cell is in, which heading rows sit above each position. The filed layer stores rows and cells but not this |
| 2 | Units and signatures | One row per column, heading, text shape and footnote marker per filing, each with a signature |
| 3 | Apply, with the rules the wrappers already hold | The reference-rate column, rate codes, industry labels and the rest (73 vocabulary and 7 source rules loaded for the five funds). Measured against production (T7) |
| 4 | Match and worklist | Covered, not covered, changed; the bundles written out as a file |
| 5 | The model pass and its prompt | One prompt template with slots for the unit, the options and the form of the rule |
| 6 | Acceptance | Section 11 |

Text fields join the spine at one point: the table with one row per position and field
(`int_field_read`). A text field is another row there with source "printed" and its rule. Nothing
after that point needs to know the difference.

Patterns are data and SQL applies them. Where a shape is too irregular for one pattern, a small
Python step whose output dbt reads is added, the same arrangement as the filing parser and the
wrapper loader. That is added when a real case needs it, not before.

## 7. The prompt

Shared across uses: the role, the bundle layout, the instruction to write a rule, the "cannot tell"
answer.

Written and tested per use: the closed list of answers and their definitions. Measured reason
(section 10): a redesigned set of rate options fixed the PIK cells and broke the spread cells, and
neither effect was visible until it was run. Each use's options get a small labelled test set
before they are relied on.

## 8. Order of the uses

1. Rate cells and column headers. They are where Blue Owl and Apollo keep fields production cannot
   read from tags, and they have the strongest independent checks.
2. Heading rows (industry, sections).
3. Footnote markers, issuer names and instrument wording. No arithmetic check exists for these.

## 9. How text is read today

Read from module structure and the wrappers on 2026-11-19; not an audit of every function.

| # | Mechanism | Reads | Yields | Fund-specific part |
|---|---|---|---|---|
| 1 | Label patterns in the wrapper | The label in the tag | Issuer, instrument, industry, row role | Each wrapper's own strip lists, split patterns and marker lists |
| 2 | The page reader (`pipeline/bdc_xbrl_html_bridge.py`) | The printed row carrying a position's fair value | Reference rate, margin, maturity, instrument type, industry | Wrapper names the column and the codes; reading logic is general code |
| 3 | Section bridges | The printed section a row sits under | Instrument context the tag lacks | A file of exact entries per fund, filing and label |
| 4 | Classifiers | Instrument and label wording | Instrument type and lien | General code with word lists |
| 5 | Row corrections | The printed line, read by an agent | Any field, one row at a time | All of it |
| 6 | Agent A | The rate part of the label | Reference rate, spread, rate, PIK rate, maturity | A grammar and an anchor file per fund, outside the wrapper. Not merged; used for flags. Apollo only among the five |

Of the 3,911 row corrections for the five funds, most are text fields: issuer name 401, reference
rate type 399, industry 328, spread 269, coupon type 246, instrument description 212.

Carried over: the page reader's anchoring on the row that holds the position's own fair-value fact;
its per-field parsers for dates, rate codes and margins; its per-field status; the classifiers'
word lists as general vocabulary; Agent A's method and its rule that an existing value may be wrong
and must not be fitted to.

Not carried over: guessing a field from cell content when the header is unclear; bridge files keyed
to exact labels in one filing; output held in stores outside the wrapper.

## 10. What has been measured

All on text of the five funds. Agreement is with reference labels that are themselves derived from
tag counts and production output, so it is agreement, not correctness. Files: `scratch/2026-11-19_jev_text/`,
`_v2/`, `_v3/`, and `scratch/2026-11-19_agent_text/`.

| Run | Items | Agreement on the 144 strong-label items | Notes |
|---|---|---|---|
| Jev, thin context | 204, each sent twice | 120 (83 pct) | Most misses traced to missing context |
| Jev, rich context | same | 126 (88 pct) | Headings 66 to 71 of 73; headers 41 of 50 both times |
| Jev, rates only, two-by-two | 31 rate items | Old options with rich context best: 17 of 21 | The regression in the rich-context run came from the redesigned options |
| Sonnet agent, rich context, one run | 204 | 139 (97 pct) | 153k tokens, under 2 minutes. Headers 46 of 50, headings 73 of 73, rates 20 of 21 |

- Under a strict acceptance rule (both option orders agree, not "cannot tell", confidence at least
  0.9) Jev accepted 91 of 144 with no disagreement, and only 9 of 21 rate items in any setting.
- The Sonnet agent's confidence is self-reported. At 0.9 it accepted 118 of 144 with no
  disagreement; at 0.8 it accepted three that disagreed. It was run once, with no reversal of
  option order, so its stability is not known.
- A text pattern is the wrong unit for rates: the same bare "N%" holds different things in
  different columns. The unit is the shape within its column (section 4.1).
- Base rate plus spread reproduces the filed all-in rate within a quarter point on 96 to 99 pct of
  SOFR rows at 2026-03-31 for Ares, BCRED and HPS (`intermediate_spine.md` section 10).

## 11. Open: how a rule is accepted (parked by the owner)

Recorded so the discussion is not lost. Nothing here is decided.

- A gate has two layers. A common layer for every use: coverage per quarter; every quarter passes
  on its own and not as a pooled average; a rule never changes a tagged value; invented cases that
  must not match; same input, same output. And one independent check per use, which the agent
  cannot satisfy by editing its own output and which is never "agrees with production".
- Candidate independent checks, with their strength as judged, mostly unmeasured:

| Use | Check | Strength |
|---|---|---|
| Rate cells | Cash plus PIK equals the total; spread plus base rate equals the all-in rate | Strong; the second is measured |
| Column headers | The tags on cells under the header match the field named | Strong where the filer tags that column; none where it does not |
| Heading rows | Printed subtotals under each heading equal the rows beneath | Medium; only where printed |
| Reference-rate codes | The filing's own legend; spread plus base rate | Medium |
| Table captions | The table's rows sum to the total it reports | Medium |
| Footnote markers, issuer names, instrument wording | Nothing arithmetic | Weak |

- The uses that need text most have the weakest checks: a column is read from text because the
  filer does not tag it, which is when the tag check is unavailable.
- Where the check is weak, the working assumption is that the owner accepts each rule once. That is
  still one decision per rule, not per row.

## 12. Outstanding items

Decisions for the owner:

| # | Item |
|---|---|
| 1 | DECIDED (T8): a gate per extraction or classification. Still open within it: the check for each use, and who accepts a rule where no strong check exists |
| 2 | DECIDED (T9): Sonnet sub-agents first, Haiku tested too. Still open: whether Jev has a role (T5). Tests to run: the same items with Sonnet and Haiku, each twice with option order reversed; Jev as a yes/no check on new vocabulary (for example "is this an industry label"), scored on false accepts against the labels in the wrappers and negatives from the same filings |
| 3 | RESOLVED: one model round per pass. Dependent units are bundled with their parent (section 4.1), so no second round is needed; detection is re-run after acceptance only as a check |
| 4 | DECIDED (T13): stop that fund's build by default. Example: a filing starts printing a second line under each industry, the proposed rule for the new level is not accepted, and 400 positions have no settled heading path; that fund stops until a rule is accepted or the owner raises the ceiling. A new name in a known slot is not this case (section 4.1a) |
| 5 | DECIDED (T10): test Agent A's files for usefulness; fold in if useful, redo if not. Still open: the test itself (proposed: apply each grammar through this method and score it against the row corrections of T11 and the tagged values) |
| 6 | DECIDED (T11): the row corrections are an imperfect test set. Still open: what share reproduced by rules counts as good enough, and how a disagreement between a rule and a correction is settled (the printed line decides, not either of them) |

Not yet measured or designed:

| # | Item |
|---|---|
| 7 | How often each of today's mechanisms (section 9) is the one that supplies a published value. Measurable from production's provenance columns; it says which mechanism matters most |
| 8 | Page structure: whether heading rows and column positions can be worked out reliably from the filed layer. Column and row spans were checked on a test fixture only |
| 9 | Signatures: what makes two columns, headings or shapes "the same" across quarters and across funds |
| 10 | Whether printed cells reproduce Blue Owl's 202 relabelled contexts and Apollo's 57 untagged values, which would turn those corrections into rules |
| 11 | Stability of a general agent: repeat runs and reversed option order on the same items |
| 12 | How far SQL patterns go before a Python step is needed |
| 13 | The medium and weak checks in section 11. Only spread plus base rate is measured, on one quarter |
| 14 | The current state of Agent A: whether anything was merged after 2026-06, and how many funds have a grammar that passes its gate |
| 15 | Footnote status. Non-accrual carried by footnote was a known gap for the five funds; no measurement here |
| 16 | Reference tables for base rates other than SOFR (belongs with `intermediate_spine.md` section 10) |

Dependencies:

- The spine reproduces production first (T7 and the owner's "compare like for like").
- Page structure (section 6, item 1) comes before everything else in this spec.
- The gate (section 11) must be settled before any rule written by an agent is published.
