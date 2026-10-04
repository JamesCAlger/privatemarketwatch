# Remaining bundle work

Basis: `note_formula_v4_48`, 67 selected natural flags across 11 funds.
There are 39 evidence-ready and 28 blocked bundles. Three ready bundles exceed
the runner's size proxy cap. Readiness is not an independent audit.
The blocker profile counts each flag once per cause; causes overlap and must not
be summed into a distinct-flag total.

| Evidence gap | Flags | Funds | Implication |
|---|---:|---:|---|
| Annotated section scope unresolved | 10 | 3 | Preserve ownership/section ambiguity. Do not infer a new section boundary merely to improve coverage. |
| Referenced note table missing | 2 | 1 | Other unresolved causes also remain; a missing table cannot be waived. |
| Proxy cost needs lineage | 6 | 4 | Requires a different evidence contract; a current reported-cost comparison cannot validate a derived value. |
| Conflicting cost/FV scales | 4 | 1 | Known TCW mechanism; retain B1 investigation and independent normalization evidence. |
| Missing referenced notes | 1 | 1 | Recover the correct filing note block; do not borrow a matching marker from another period. |
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

## Missing-note investigation: distinguish definitions, references and operators

Three existing flags exposed different mechanisms:

- **Jackson Paper, Onex, Q4-2023:** a holdings cell containing only
  `(5) (7) (8) 10) (11) (13)` was mistaken for a note definition. Its apparent
  block at table 44 hid the real explanatory notes following table 45. Requiring
  explanatory alphabetic text excludes numeric/alphabetic reference-only lists.
  This recovers the source notes without borrowing across an actual earlier note
  block. Notes 7/8 concern commitments; note 11 explains negative cost from
  capitalized discount. The source cost at t44r5 remains -16,223.
- **Spotless Brands, Ares, Q3-2023:** `Principal Amount**` was parsed as `*`.
  A word-boundary restriction dropped the first attached symbol; it could also
  miss an attached single symbol entirely. Preserving the full suffix retrieves
  the actual double-star currency note. Single- and double-star definitions are
  kept distinct.
- **Amerivet, Ares Strategic Income Fund, Q4-2024:** note 12 is present after
  table 90, beyond the bounded gap from the last investment table (82).
  Intervening tables include derivatives, an affiliate schedule, five pages of
  loan commitments and an equity-commitment table. The gap limit was not widened:
  supporting this requires a scoped continuation contract, not a larger arbitrary
  table allowance. The flag also retains a visible/context share-class conflict.

The attached-symbol repair initially exposed four Oaktree false note references:
`SOFR+` and `E+` in an **Index** column, immediately followed by a percentage in
**Spread**. The final rule treats that explicit column pair as a formula. It
requires matching header/data geometry, a recognized benchmark abbreviation and
a percentage spread. Unknown codes, wrong headers, absent/untagged-number spreads
and superscript plus signs retain the note requirement. A generic trailing plus
is not globally ignored. Original headers, cells and rate legends remain in the
bundle for review.

These are reusable parsing mechanisms observed in particular development cases,
not filer-specific eligibility overrides. Source amounts, candidate inventory and
identity evidence are checked separately from changes to note retrieval. The
same-period/nearest-real-note-block guard remains in place. No model observations
are transferred to a revised request, and no independent audit is implied.

The original inspection is preserved as
`missing_note_inspection_0888fd84680be8dc.json`. Replays 46 and 47 retain the
intermediate definition and symbol changes, including the four temporary formula
false positives; they are not erased from the experiment history.

Final replay `note_formula_v4_48` has 39 ready / 28 blocked, versus 37 / 30 before
these repairs. `note_retrieval_delta_81bc15759cef6169.json` verifies that only the
two recovered flags change note evidence relative to replay 42; source identity,
amounts and candidate sets are unchanged across all 67. The four Oaktree cases
return to their earlier evidence. Historical model scores do not transfer.

Offline request sizing adds a separate operational limit: three Ares C107 packets
use 22,361, 24,464 and 25,355 whole-request cl100k proxy tokens, above the runner's
22,000 cap. Spotless is the first of these; Jackson uses 6,906. Thus 36/67 meet
both evidence and size requirements, before confidence or independent review.
Do not truncate notes or drop sibling candidates merely to fit the cap.

Validation: 391 targeted Jev tests pass; the 23rd bounded production metadata
audit reports zero changed paths. No full suite, production rebuild/export or
production-writing semantic diff was run. No new API calls.

## Headerless declared-context anchors

The three `no_current_period_candidates` cases are not simply failed issuer-name
searches. The declared contexts locate source rows, but their HTML tables have
no locally recognised header band:

| Case | Source anchor | Finding | Remaining boundary |
|---|---|---|---|
| MES Intermediate, Varagon, Q4-2025, C104 | t55r6 | Revolver FV is explicitly tagged `fixed-zero`; source cost is -2,000 | Headerless table; the neighbouring inspected tables are also headerless. Whole-row scope, columns and sibling coverage are not certified by one zero fact. |
| Krayden, Varagon, Q2-2023, C107 | t11r51 | Visible row is a revolver with 0% interest; its context describes a term loan at 11.34%. Cost uses `ck0001784700:InvestmentOwnedAtCostNetOfCapitalizedDiscount`, sign minus, scale 3 | Headerless table, unresolved table period and a substantive identity contradiction. Custom-concept interpretation must also be explicit. |
| CMG Holdco, Crescent, Q4-2025, C107 | t36r7 | Visible delayed-draw position has source cost -20,000, FV -51,000, maturity 11/2030. The preceding table 35 has headers | Headerless continuation cannot inherit columns and ownership solely from adjacency or matching values. Comparative CMG rows are a different period and remain excluded. |

No readiness or reference labels changed. Any future header-continuation support
must retain the original header table/row coordinates, demonstrate unchanged
geometry and owner/period scope, and stop at new headings or conflicting facts.
It needs counterexamples for inserted columns, different accounting owners,
comparative periods and custom-concept ambiguity. Finding the output's context
is a retrieval aid, not proof that the context correctly identifies the position.

The raw review helper previously listed only standard cost/FV concepts as
`source_positions`, leaving Krayden's custom cost out of that view. It now also
records **all exact-context numeric facts**, with original attributes, markup and
coordinates, without assigning them a cost/FV meaning. This preserves custom
concepts, nil/excluded content and unlocated facts for review. Eighteen focused
source-review tests pass, including exact-context isolation and bounded refusal
instead of silent truncation.

Artifacts: `header_gap_inspection_2a9e9202913a7d5a.json`,
`unmatched_cost_sources_50.json`, `unmatched_zero_source_50.json` and
`custom_context_source_51.json`. These are bounded source investigations on the
same three frozen flags, not new natural cases or independent audit certificates.

## The remaining note-table gap crosses a page boundary

Both remaining missing continuations are AB Centers C107 flags for CIK 1959568,
Q3-2024. Note 9 refers explicitly to the following unfunded-commitments table.
Between that note and table 15 are note 10, the page footer, a repeated owner
heading, an explicit continued schedule title, the same date/units, and a new
unfunded-commitments introduction. Table 15 contains 62 rows and 4,471 text
characters. The immediate-adjacency and 40-row limits both exclude it.

This is different from the supported reference-rate-table association. A future
commitment-table contract could use the repeated owner/date and explicit continued
heading, but must retain intervening text, preserve all rows or demonstrate
relevant-row recall, and stop before the subsequent comparative schedule. The
current rate-specific exception and generic size limits were not broadened.
Both flags also have unresolved annotated section scope, so table recovery alone
would not make them evidence-ready.

Artifact: `note_continuation_inspection_3f5a3d4abff61e39.json`. It contains bounded
navigation excerpts, not a complete table bundle. The raw source is unchanged.
The linked [proxy-cost investigation](07_proxy_cost_evidence.md) now also records
possible main/supplemental row overlap, a separate question from whether each
reported negative cost matches its source.

## 2026-10-04: role-helper coverage across existing filings

The offline role helper was applied to 51 distinct candidate tables from 23 cached filings, covering all 11 funds with retrieved candidates. It recognized 14 position-value tables across five funds and returned unknown for 37 tables across six funds. No table was classified as ambiguous or as unfunded commitments in this candidate-conditioned sample.

Unknowns include combined issuer headings (Ares, Crescent), no explicit instrument column (Monroe, CIK 1742313), symbolic note markers (Varagon), an Investment/Industry issuer convention (Goldman), and multi-marker numeric footnotes (Fortress). These are explicit limitations of the narrow helper, not proof that the underlying tables lack position data. No aliases or scope rules were widened to improve this count.

Crucially, the supplemental AB Centers commitment table is not in this candidate-table sample. It was identified by the separate four-row source investigation. Therefore these counts measure coverage conditional on existing retrieval, not schedule-role accuracy, full-filing recall or duplicate detection. A future role-aware bundle must inventory supplemental disclosures independently of the cost/FV candidate search before claiming relevant-schedule recall.

Artifact: disclosure_role_profile_a042a86bbf1a9146.json. Original headers, source hashes and table coordinates are retained. Builder, readiness, model observations and routing remain unchanged. The helper remains optional and unintegrated.

## 2026-10-04 checkpoint: explicit hidden-source content

- Six new negative fixtures reproduced a gap: explicitly hidden tables/amounts were accepted as visible source evidence. Added conservative refusal for inline display:none, visibility:hidden/collapse, HTML hidden and ix:hidden, including ancestors, referenced notes and retained continuation cells. Text and coordinates are preserved; no hidden evidence is silently dropped.
- Visible styling, empty hidden spacers and aria-hidden controls remain supported. This is not a CSS renderer: stylesheet/class visibility, overrides and other rendering semantics remain outside the check.
- Final targeted Jev suite: 454 passed, 229 parser deprecation warnings. Bundle file alone: 214 passed. The initial continuation-cell schema mistake was caught and corrected before replay.
- Replay explicit_visibility_v4_52: 39 ready / 28 blocked. Structured comparison with replay 48 finds zero changed source candidates, identities, amounts, notes or readiness decisions across all 67 flags. The builder hash and request bindings still change; no historical score transfer.
- New builder SHA-256: 50a963afa56516ffc4c59606a27b292b861da55da6bb40cf95b432e9b243aeb1. Delta artifact: note_retrieval_delta_93f671ada0fa1fc5.json.
- Current sizing artifact request_size_profile_4f68c257ba406ea4.json: 467,734 aggregate proxy tokens, max 25,355, three above cap. Optional v2 compaction reconstructs all 39 exactly at 420,686 proxy tokens, max 20,236; remains disabled/unscored. Tiny token differences versus replay 48 reflect changed version-bound identifiers, not evidence removal.
- Refreshed unfinished blind_review_inputs_53 and verified all 67 packet bindings and 26 source hashes. API accounting unchanged: 100 calls, 1,580,960 provider input tokens. No independent clearance, B1 suppression or production edits.
