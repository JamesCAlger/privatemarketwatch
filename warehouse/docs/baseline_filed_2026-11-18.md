# Filed layer baseline

Measured 2026-11-18 with `.\warehouse\dbt.ps1 build` (partial parsing off), after the fix round that followed
the final review. Parser version 3, 86 filings of the five v0.5 funds, `warehouse/data/filed/`. Holdings read:
`stg_holdings`, build of record b1116a (71,477 rows for the five funds, of which 10,740 are
`underlying_schedule`; "published" = the other 60,737).

Result line: `Done. PASS=162 WARN=11 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=173`. Step 1 stands as it was
(105 pass, 8 warn, same counts); the filed layer adds 10 views and 50 tests (47 pass, 3 warn).
Parser: 67 pytest tests pass; `--reparse` wrote 86 of 86 in 296 s; `--verify` matched 86 of 86 in 319 s.

Passing tests do not mean the data is correct. The tables are internally consistent and their row counts tie to
the manifests. The bridge tests measure where the filed layer differs from the old extractor; that is a
measurement of a difference, not agreement, and neither side is shown to be right.

An earlier version of this document (parser version 2) said the layer was complete and agreed with the old
extractor, counted 790 position facts in no row, and described the 2,009 no-fact rows loosely. The final review
found the position-fact count was short by 106 and the description of the 2,009 was wrong in part. Both are
corrected below.

## Row counts

filing 86, context 288,935, context_member 399,240, unit 1,093, tagged_fact 1,175,675, document_row 348,443,
fact_placement 1,175,675, footnote 4,479, fact_footnote 1,943,783. The counts equal version 2:
the version 3 changes alter column values and add columns, not rows.

## Structure tests (all at zero)

Primary keys unique for all 9 tables; every table's `accession` exists in `filing`; fact to context, fact to unit,
member to context, placement to document row, fact-footnote to footnote and fact all resolve; every numeric fact
has exactly one placement and every placement has a fact; every placement has the same concept and context as its
fact (1,175,675 of 1,175,675). New in this round, read from the manifests: one manifest and one filing row per
folder, one parser version (3) in all manifests and filing rows, manifest row count equals the table's row count
for every filing and each of the nine tables (a missing table file was checked to fail the test), and every filing
has a document type and a period end date (86 of 86; no baseline needed).

## Baseline tests (warn while above zero; ceiling = measured count)

| Test | Count | Ceiling | Was |
|---|---:|---:|---:|
| baseline_filed_filing_missing (dim_filing accession with no filed row) | 0 | 0 | 0 |
| baseline_filed_context_missing (published row, context not in `context`) | 0 | 0 | 0 |
| baseline_filed_fair_value_no_fact (published row, context has no fair-value fact) | 2,009 | 2,009 | 2,009 |
| baseline_filed_fair_value_ambiguous (context with several fair-value facts of different value) | 0 | 0 | 0 |
| baseline_filed_fair_value_differs (value differs, no correction naming fair_value) | 0 | 0 | 0 |
| baseline_filed_fair_value_differs_corrected (value differs, correction names fair_value) | 2 | 2 | 2 |
| baseline_filed_fair_value_null (new: published row with null fair value on a context with one filed value) | 0 | 0 | n/a |
| baseline_filed_position_fact_no_row (investment-identifier-axis fact in no kept row, not hidden) | 896 | 896 | 790 |

Matching rules: the axis is matched on its local name (`axis` ends with `:InvestmentIdentifierAxis`). Nine
filings (period ends 2022-09-30 to 2023-03-31, all five funds) use `us-gaap-supplement:InvestmentIdentifierAxis`;
the old test matched `us-gaap:` only. The fair-value concept is matched on local name `InvestmentOwnedAtFairValue`
and a namespace starting `http://fasb.org/us-gaap/`. Every filing that tags it uses the `us-gaap` prefix (five
namespace years, 2022 to 2026), so the rule gives the same rows as before. "Published" now means
`accounting_record_class` is not `underlying_schedule`, so a null class counts as published.

Accounting of the 60,737 published rows, each in exactly one bucket: 58,726 fair value equals the filed value
(to 2 decimals); 2 differ (both corrected, below); 2,009 no fair-value fact; 0 context missing; 0 ambiguous; 0 null
fair value; 0 null `accounting_record_class`. 58,726 + 2 + 2,009 = 60,737.

## What is behind the non-zero counts

**Fair value, no fact (2,009).** By fund: Blue Owl 1,955; Apollo 52; Ares 2. Five largest fund-quarters (all Blue
Owl): 2025-12-31 340 rows, 2026-03-31 337, 2026-06-30 317, 2025-09-30 264, 2025-03-31 242. For each row, the
holdings fair value was compared with every other fact on the same context (exact equality of value):

| Fund | Rows | Match another fact exactly | Concept it matches | Match none |
|---|---:|---:|---|---:|
| Blue Owl (0001812554) | 1,955 | 1,955 | `orcic:InvestmentOwnedFairValueNetOfUnamortizedFees` (all 1,955), sign included | 0 |
| Apollo (0001837532) | 52 | 8 | `ck0001837532:InvestmentOwnedAtFairValueAfterCashEquivalents` (all 8 are positive; cost and principal facts on the same contexts carry the same value) | 44 |
| Ares (0001287750) | 2 | 0 | none | 2 |

Blue Owl: 1,271 rows have fair value 0 (the fact is 0) and 684 are negative (the fact is negative; sum
-112,550,000, from the review). So "the holdings values there are negative" holds for 684 of 1,955, not all. Zero
rows also equal other zero-valued facts on the context (commitment and financial-support facts); those are
coincidences of 0 and the net-of-fees fact is the one that matches in every row. Apollo: the 44 rows have fair value
0 and no fact on their context equals it (the contexts carry cost, shares, principal). Ares: positive fair value;
the context carries only rate facts, so the value did not come from a fact on `src_context_id`. In total 1,963 of
2,009 rows match a fact of another concept and 46 match none. No other concept was substituted in the test.
Whether the net-of-fees concept is the right source is a question for the extractor owner.

**Fair value differs, corrected (2).** Both Apollo, accession 0001193125-26-215667, report date 2026-03-31:
holdings -248,000 against filed +248,000, and +1,884,000 against filed -1,884,000. The sign was flipped.

**Investment-axis fact in no kept row (896).** By fund: Blackstone Private Credit 646; Ares 135; Blue Owl 73;
Apollo 41; HPS 1. (Version 2 reported 790: 576, 99, 73, 41, 1.) Of 860,728 placements on investment-identifier
contexts, 10,293 have no row; 9,397 of those are in `ix:hidden` (Apollo only) and are not counted. Largest
concepts in the version 2 breakdown were `InvestmentInterestRateFloor` (566), `InvestmentInterestRate`,
`InvestmentOwnedPercentOfNetAssets`, `InvestmentOwnedAtCost`, `InvestmentOwnedAtFairValue` and
`InvestmentOwnedBalancePrincipalAmount`; that breakdown was not repeated for the 106 added rows.

## Version 3 measurements

- Typed members now stored as filed. The two BCRED 0001803498-22-000021 `Apex Group Treasury, LLC 1` members are
  distinct (`Apex Group Treasury, LLC 1` and `Apex Group Treasury, LLC  1`). Groups of contexts in one accession with
  the same member set (all members, same axis and text) and the same period, where the set includes an
  investment-identifier member: Ares 13, BCRED 30, Apollo 3, HPS 9, Blue Owl 0; 55 in all (the review counted 65
  with the collapsed text). Their identical text is now the filed text; whether they are genuine duplicate contexts
  was not checked against the raw files.
- Hidden facts (`in_hidden`) with a printed element pointing at them (`shown_row_index` set): Ares 953 of 1,078,
  BCRED 27 of 145, Blue Owl 35 of 126, Apollo 9,721 of 9,969, HPS 22 of 107. All 9,397 hidden investment-axis
  facts get a shown row.

## Shape of `src_context_id` (five funds, 71,477 rows)

- Null or blank: 0. More than one id in a cell (`;`, `,`, `|`, space): 0. Every row holds exactly one id.
- Each (accession, id) pair belongs to exactly one holdings row: 71,477 distinct pairs for 71,477 rows.
- Form: 7,298 ids look like `C_<guid>`, 64,179 are other filer-chosen ids (for example `c-1308`).
- The task mentioned 222,355 universe-wide rows that merge several contexts. None of the five funds' rows has more than one id, so no row needed an untieable count. The other funds were not looked at.

## Fair value rule

For each (accession, context) the filed value is the `value_numeric` of the `InvestmentOwnedAtFairValue` facts of
the us-gaap namespaces on it. If the facts on a context carry more than one distinct value, the context is
ambiguous: it is counted in `baseline_filed_fair_value_ambiguous` and left out of the difference tests. A context
whose fair-value facts are all nil counts under `no_fact`. Otherwise the value is the (single) value. Comparison:
exact after casting both sides to DECIMAL(38,2).

- Contexts with more than one fair-value fact, whole filed layer: 1,315; of those 106 carry different values (version 2 measurement).
- Holdings rows on a context with more than one fair-value fact: 10 (all same value); on one with different
  values: 0.
- Rows with a correction recorded: 2,089; 2 of them name fair_value (the test is a `like '%fair_value%'` match on the field list; a token such as `fair_value_usd` would also match).

## Not checked

- Whether the filed fair value is the right figure for a position (only that it equals the pipeline's).
- Any field other than fair value (cost, principal, rate, maturity, names) against the filed layer.
- That `document_row` cells hold what a reader sees, including the column a cell sits in (colspan and rowspan are
  stored, not applied). The row-less facts were counted, not inspected.
- Whether the 55 equal-member context groups are real duplicates in the filings.
- Funds outside the five; filings that are not in `dim_filing` (12 filed filings have no holdings rows).
- Filed values against the printed page beyond what earlier reviews did.
