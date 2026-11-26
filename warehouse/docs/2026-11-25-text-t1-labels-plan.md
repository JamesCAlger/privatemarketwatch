# Text slice T1 (the label: issuer and instrument): plan, for owner review

Date 2026-11-25. Branch `warehouse-text-spec`. Spec: `docs/text_fields.md` (method in section 5, measurements in
section 6). Nothing here is built. Build starts on the owner's go.

Agreement with production is not correctness. T1 compares names with production's; it checks no name against a
page except where a task says so.

## Superseded in part (2026-11-26)

Written without the 2026-11-19 spec (`text_fields_spec_2026-11-19.md`) or Agent A. See `text_fields.md` section 0.
Before any task below is built, the plan changes as follows; it is to be rewritten once the owner settles the order:

- New task 0: test Agent A's Apollo grammar and anchors (apply through this layer; score against tags and the row
  corrections). Fold in if useful (19-T10).
- Task 2: no new format. Agent A's grammar format, stored in the wrapper's `reading_rules`. Load the wrappers'
  existing split patterns first and measure them (19-T7).
- Task 4: agents write only what the existing rules do not cover. Sonnet and Haiku on the same bundles.
- Task 5: Apollo's anchor file already lists its industry names; start there.
- Task 7: corrections are a test set first (19-T11); only the unreproduced remainder is applied.
- Acceptance: a name pattern is accepted by the owner once per fund and format, not by agreement with production.

## Goal

For every position: the label as filed, split into parts by a rule that is named, dated and tested. Parts:
`affiliation`, `row_number`, `issuer`, `instrument`, and for Apollo also `industry`, `brand`, `rate_text`,
`maturity_text`. The parts, put back in order, give the label.

Out of T1: the class, lien and type of an instrument text (T2); reading the rate text (T3); the industry mapping
(T4). T1 only cuts the label.

## What the measurements say (spec section 6)

- 18,494 distinct labels; a hand-written pattern agrees with production on 98.3%.
- About 713 distinct instrument texts; 0 to 20 new per fund per quarter.
- Four of five funds changed label format in the last year: a pattern has dates.
- BCRED and HPS labels mostly carry no instrument.
- Apollo's industry, brand and issuer run together with no separator: the hard part.
- Blue Owl: 200 labels are relabelled by the wrapper before production splits them.

## Tasks

Each task: implementer, then an independent reviewer, as in slices 1 to 5. Each ends with a full build and a
baseline entry.

| # | Task | Output | Check that it worked |
|---|---|---|---|
| 1 | Apply the 202 relabel corrections to the label (they are parked as `deferred` today). The filed label stays beside the relabelled one | `int_label` (accession, context): filed label, label after relabels, the correction id | 202 applied; no other label changes |
| 2 | Pattern format in the wrapper copy: a list of dated patterns per fund, each with its separators, markers and part names. Loader reads it. Global default: strip affiliation, strip row number, whole text is the issuer | wrapper section `label_patterns`; loader version up; `stg_label_pattern` | Loader tests; every published label matches exactly one pattern by date |
| 3 | The split model: applies the pattern, then the dictionary anchor (longest tail that is a known instrument text). Outcome per label: `split`, `no_instrument` (pattern says so), `unparsed` | `int_label_part` (accession, context, part, text, rule); `int_label_outcome` | Parts rebuild the label on every row (test, ceiling 0); `unparsed` under a ceiling per fund |
| 4 | Agent run 1, patterns: one subagent per fund proposes its patterns from the first half of the quarters; the checks run on all quarters. Compared with the hand-written candidate of section 6.1 | Accepted patterns in the five wrapper copies; a report per fund | Parse share per fund and quarter; agreement with production; the bar is set here |
| 5 | Apollo head: split "Industry Brand Issuer". First measure whether the printed page prints them in separate cells; if so read them there and use the label only as a check. If not: industry by a list of the fund's industry labels, brand by the page or left unsplit | Apollo parts `industry`, `brand`, `issuer`; a note on what the page prints | Against production's issuer on uncorrected rows; against the page on a sample of 50 |
| 6 | Stored splits: store format, the three acceptance checks, and agent run 2 on the labels left `unparsed` or flagged malformed | `seeds/` or wrapper store `label_splits`; accepted entries | Every entry passes the checks; none keyed to a row |
| 7 | Apply the parked name corrections (613: issuer 409, instrument 220 targets, as counted in spec section 4) on top of the split, as slice 5 does for amounts | issuer and instrument in `int_field_corrected` | Outcomes under ceilings; none left `deferred` for these two fields |
| 8 | Compare with production: `cmp_name` (issuer, instrument), a cause for every group of differences; the work queue table (texts with no entry, labels unparsed, parse share) | `cmp_name`, `int_text_queue`, baseline doc | `not_yet_explained` 0 or under a ceiling with rows named |
| 9 | Records: README section in plain words, HANDOFF, changelog, CI fixture labels | docs | CI green |

## Agent runs (tasks 4 and 6)

- Run by the controller as subagents. Model: the smallest that passes the checks; start with Haiku, move to
  Sonnet for a fund only if its pattern fails the bar twice. Never Fable.
- An agent gets labels and the tagged values of their rows. It gets no production names (so it cannot copy them)
  and no network.
- An agent returns data (a pattern, a split), never code that runs in the build.
- Nothing an agent returns is accepted by the agent. The checks of spec 5.3 decide; the rest comes to the owner
  in one batch at the end.

## Owner questions (answer before the build)

| # | Question | Recommendation |
|---|---|---|
| 1 | Production "normalises" names (casing vote per fund, a strip of legal-form noise). Hold the issuer exactly as filed, or normalised? | Hold it as filed. Normalising for matching is position identity (D3), not T1. Differences in casing only are a `convention` |
| 2 | Where production is wrong and the split right ("Cadence - Southwick, Inc."): accept the difference as `old_wrong`? | Yes, each case listed with its label |
| 3 | The trailing row number ("First lien senior secured loan 3"): keep it as its own part? | Yes. It tells two tranches of one issuer apart; dropping it loses information production also keeps in places |
| 4 | Parse-share bar for accepting a pattern | Set after task 4's numbers; proposed starting point 99% per fund and quarter, with every `unparsed` label listed |

## Not in this plan

- Any change to production, its wrappers or its stores.
- Network access, SEC downloads, or a model call inside a build.
- Position ids and matching.
