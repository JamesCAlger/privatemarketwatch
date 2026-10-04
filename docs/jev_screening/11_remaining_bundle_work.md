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

## Reuse observed across filers

The current builder has no CIK-specific readiness overrides or named-filer parsing
branches. Its rules recognise evidence/layout patterns. That is an implementation
property, not proof that every pattern generalises. A read-only profile of the
same 67 packets gives the following observed feature coverage:

| Feature present in a candidate | Distinct flags | Funds | Filings | Whole packets ready / blocked |
|---|---:|---:|---:|---:|
| Monetary header spans multiple columns | 51 | 10 | 22 | 33 / 18 |
| Explicit inline negative sign | 36 | 8 | 17 | 25 / 11 |
| Explicit zero transform | 8 | 4 | 7 | 7 / 1 |
| Immediately following note table | 6 | 3 | 6 | 5 / 1 |
| Later reference-rate table across bounded intervening notes | 7 | 1 | 3 | 3 / 4 |
| Period obtained from inline instant contexts | 9 | 2 | 5 | 4 / 5 |
| Section evidence from another table | 10 | 3 | 5 | 4 / 6 |

Features overlap, and one packet may contain several candidate layouts. These
counts must not be summed. Ready/blocked describes the entire packet; a blocker
may be unrelated to the listed feature. All 55 packets with candidates contain
referenced notes, across 11 funds and 23 filings; 12 packets have no candidates.
Neither feature presence nor readiness establishes an independent evidence audit.

The multi-column, sign, zero and adjacent-note mechanisms have observations in
several filers. The newer reference-rate association has only Crescent evidence;
hold out a different filer with that pattern before claiming transfer. The narrow
raw-dimension prefix comparator is also an observed normalization mechanism, not
proof that all identifier normalization is safe.

This supports a common parser plus explicit evidence contracts, while retaining
B1 for unsupported mechanisms. Measure maintenance by the new structural pattern
and its regression cases, not simply by counting how many filers have ever needed
attention. If each additional filer still requires bespoke extraction or manual
scope reconstruction, automatic coverage can remain too expensive despite cheap
Jev calls. No maintenance return has been established here.

Artifact: `mechanism_profile_7378f0315211e1fa.json` in the pilot root, produced by
the isolated `scripts/profile_jev_mechanisms.py`. This is a candidate-sample
inventory, not a census of full filings, certified templates or future support.
