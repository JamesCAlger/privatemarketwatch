# Remaining bundle work

Basis: `rate_note_scope_v4_42`, 67 selected natural flags across 11 funds.
There are 37 ready and 30 blocked bundles. Readiness is not an independent audit.
The blocker profile counts each flag once per cause; causes overlap and must not
be summed into a distinct-flag total.

| Evidence gap | Flags | Funds | Implication |
|---|---:|---:|---|
| Annotated section scope unresolved | 10 | 3 | Preserve ownership/section ambiguity. Do not infer a new section boundary merely to improve coverage. |
| Referenced note table missing | 2 | 1 | Other unresolved causes also remain; a missing table cannot be waived. |
| Proxy cost needs lineage | 6 | 4 | Requires a different evidence contract; a current reported-cost comparison cannot validate a derived value. |
| Conflicting cost/FV scales | 4 | 1 | Known TCW mechanism; retain B1 investigation and independent normalization evidence. |
| Missing referenced notes | 3 | 3 | Recover the correct filing note block; do not borrow a matching marker from another period. |
| Missing output identity | 3 | 1 | Requires upstream identity investigation; amounts or row ordinals cannot establish the position. |
| No current-period candidate | 3 | 2 | These also have an omitted declared-context anchor; fallback must preserve the uncertainty. |
| Visible/context share-class conflict | 1 | 1 | Matching values cannot settle the identity contradiction. |

Twelve blocked flags have no candidate rows, including pre-retrieval rejections.
Five have at least one complete-looking candidate alongside unresolved evidence;
that is not permission to discard incomplete siblings. Numeric currency/scale
failure codes are retained individually in the machine-readable profile.

## Priorities and trade-offs

1. Investigate note-table and section-scope mechanisms first. They affect more of
   this selected sample than additional parser syntax support, and the source
   can sometimes establish the association without a filer-specific override.
   Every relaxation needs counterexamples for wrong periods, competing references
   and scope changes. A larger context is useful only if its association is sound.
2. Keep proxy-cost and missing-identity cases with B1. Reconstructing donor lineage
   or upstream position identity is a different investigation from checking a
   disclosed current-quarter amount. Forcing those into the current contract would
   turn cheap classification into unsupported adjudication.
3. Keep known source contradictions blocked. Do not count a correct Jev verdict
   on a malformed bundle as evidence that normalization or identity is valid.
4. Measure newly supported cases as development repairs. The earlier two-fund
   holdout has been consumed; restoring readiness cannot create a fresh holdout.

No blocker count establishes production prevalence, maintenance return or safe
clearance yield. This profile is an engineering worklist, not an instruction to
make every bundle pass. No production changes or new API calls were made.


## Measured note-table repair

A bounded association now recognizes the next reference-rate table across at most
four noncompeting footnotes, requiring at least two named reference rates in both
paragraph and table, the expected header, bounded rows/text and no conflicting
date. Intervening notes are retained. Competing table references, unknown prose or
scope changes block the association. Generic note tables still require adjacency.

This added tables to seven Crescent bundles across three filings. Three December
2025 C107 cases regained readiness: Accurate Finance Sub, CRS TH Holdings and CCI
Buyer. Four other bundles remain blocked for section scope. The overall split
moved from 34/33 to 37/30 without changing source identities, amounts or candidate
sets. No new model calls, independent certificates or B1 savings were recorded.

## Observed section repetition across Crescent filings

The sampled Q4-2025 pages for Accurate Finance Sub and CRS TH Holdings repeat the
annotated `Investments (1)(2)(3)` heading locally. In sampled Q3-2025 and Q1-2026
pages, later tables instead inherit that heading from the first table without an
explicit continuation marker. The latter retain an unresolved-scope blocker.
Both sets repeat the fund name and schedule title; that alone is not used to
assert unchanged accounting scope. These are different sampled positions/pages,
not a complete template census or a matched-position longitudinal test.

Layout profiling now records whether section evidence is local or from another
table, its unresolved-scope reason and the association used for note tables.
This separates geometry drift from evidence-scope drift without certifying either.
The conservative continuation rule has not been relaxed to recover more flags.
