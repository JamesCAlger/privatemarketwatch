# Remaining bundle work

Basis: `dependency_bound_v4_55`, 67 selected natural flags across 11 funds.
Its structured evidence and blocker counts are unchanged from replays 48 and 52.
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

## 2026-10-04: source-wide disclosure-role inventory

The bounded inventory now scans every table in all 26 selected cached filings, using the frozen source-first review inputs to include filings absent from early-refused bundles. It inspects 2,641 tables: 184 have explicit position-value headers, six have explicit unfunded-commitment headers, and 2,451 are unknown to the deliberately narrow role helper. These counts include other periods, owners and irrelevant tables; they are not relevance or accuracy scores.

Only 14 of the 190 recognized tables are in the existing candidate-table inventory. All six commitment tables are outside it, in two Senior Credit filings: Q3-2024 tables 15/18 and Q1-2026 tables 19/20/30/31. The parser associates Q3-2024 with table 15, leaves table 18's period unresolved, associates Q1-2026 with 19/20, and Q4-2025 with 30/31. These are retained parser findings, not independently certified scope.

An initial pass using only declared builder paths covered 25 filings and found two commitment tables. The source-first bindings add the Senior Credit Q1-2026 filing represented by an early-blocked proxy-cost case: another 73 tables, including 16 position-value and four commitment tables. This demonstrates why a builder-conditioned inventory cannot establish coverage of all selected filings.

Design implication: create a cached, source-wide disclosure inventory before selecting evidence for an individual rule. Preserve unknown roles and unresolved owner/period associations. Use the inventory to test whether relevant supplemental disclosures were considered, not to append every table or automatically certify recall. Current candidate packets and readiness remain unchanged; no source truth, duplicate exposure or inclusion correction is inferred.

Artifact: disclosure_role_profile_1e72bd5b76d52c95.json. Earlier 25-filing diagnostic: disclosure_role_profile_dbb4aad701f83096.json. The final report binds the prepared review manifest, parser and role-helper hashes, verifies all 67 prepared packet bindings, and checks each source hash before/after parsing. Unknown-table counts are retained; their full cells are deliberately omitted from this diagnostic. No new funds, model calls or production changes.

## 2026-10-04: stylesheet visibility scope check

A bounded lexical scan of all 26 hash-bound cached filings found no embedded style blocks, stylesheet link tags or CSS imports. Consequently it found no stylesheet visibility declarations to investigate in this selected sample. Artifact: stylesheet_inventory_e2984c3f87a80287.json, generated offline by scripts/inventory_jev_stylesheets.py with all 67 prepared packet bindings checked.

This does not certify rendered visibility: the scan is not a browser, does not resolve CSS syntax/cascade or scripts, and fetched no external resources. The builder's existing positive inline/HTML hidden-content refusal remains unchanged. Stylesheet-driven layouts remain an explicit future-layout limitation; this result provides no reason to add a CSS renderer to the current pilot. No new model calls, readiness changes or production edits.

## 2026-10-04: optional explicit rollforward role

Extended the isolated disclosure-role helper to recognize a same-band Name of Investment header, two valid chronologically ordered dated fair-value headers, and both Gross Addition and Gross Reduction columns. It preserves original header text/coordinates and dates. Missing movement fields, malformed/reversed/equal dates and unsupported geometry remain unknown; duplicate movement headers are ambiguous. No ownership, economic identity, inclusion or correction is inferred.

Twenty-three focused helper tests pass, including ten new rollforward checks. In the separate exploratory TCW filing, the helper identifies table 5 as position_values and table 10 as investment_rollforward (exploratory_table_roles_4cf31ed60a1d39fe.json). This is one source example, not cross-filer rollforward validation.

Reprofiling all 26 original frozen filings yields exactly the previous counts: 2,641 tables, 184 position_values, six unfunded_commitments, 2,451 unknown, no recognized investment_rollforward tables. Artifact: disclosure_role_profile_e683ca5c6be6746b.json. The additional rule therefore adds no demonstrated coverage within the frozen sample. Header conventions beyond this positive example remain unsupported; aliases were not widened to improve coverage.

The helper is optional and unintegrated. Builder/request versions, 39/28 readiness, the frozen 67-case experiment, 100-call accounting and zero independent clearances are unchanged. The separate TCW exploration remains outside those denominators. No full suite, production rebuild/export or production-writing semantic diff was run.

## 2026-10-04: supplementary disclosure navigation

Added an optional table-search helper that retains exact-context anchors and contiguous issuer-phrase matches across all parsed table roles and periods. It preserves source cells, header evidence, context definitions and original coordinates, including unknown/hidden content. Search limits refuse incomplete results rather than silently truncating. This is navigation, not sibling identity, independent recall or a model-ready bundle; no existing candidates are replaced.

Across the same 67 development flags and 26 source files, exact published-name search succeeds for 65 cases and refuses two one-word names. Forty-six have lexical matches; all 65 have an exact-context anchor. Fifty cases have navigation coordinates absent from their builder candidates, while 14 have builder coordinates missed by this search. These are complementary retrieval results, not 50 improved bundles. Exact-anchor fallback also preserves the two refused-name cases.

A separate source-column method reads the issuer cell only where an exact-context row has explicit, separate issuer/instrument headers. It preserves the unmodified text and provenance; unknown/hidden headers, combined investment descriptions and unsupported names remain unresolved. It supplies queries for 23 flags across four funds and adds coordinates beyond published-name search for 11 flags across three funds. The additions include other instruments, comparative periods and tables with unknown roles. They require relevance review and do not certify complete evidence.

Concrete examples: AB Centers' source issuer column recovers the clean name from both polluted commitment-row labels, finding three main-schedule rows plus two commitment rows without Petvet. TCW's separate exploratory position remains unsupported by automatic source-column recovery because its rollforward header is Name of Investment and combines issuer/instrument/rate. A manually source-confirmed Superior Industries phrase finds nine mentions, including the primary schedule, comparative rows and other disclosures; that manual arm is not automatic coverage. For Oaktree BioXcel, broader navigation includes loans, common stock, warrants, acquisition-date tables and both current/comparative schedules, illustrating why a borrower match cannot select a position.

Artifacts: disclosure_search_profile_da03743e49495fec.json (all 67) and disclosure_search_31d4e77534df5bba.json (two investigated sources). Earlier published-name-only profile ddb2f2b271e77fcf is retained. Twenty-seven focused search/seed tests pass. The helper remains unintegrated; replay dependency_bound_v4_55, 39/28 readiness, request payloads and 100-call accounting are unchanged. No independent audits or production changes.

## 2026-10-04: header-continuation geometry probe

Added an optional, non-mutating diagnostic for a headerless table between two tables with identical issuer/instrument/cost/FV header text and column spans. It requires agreeing table periods, checks every recognized monetary local-name fact against the proposed columns, and requires matching context period/entity. Hidden content, unsupported layout, shifted columns, missing fields and conflicting contexts remain unresolved. The result never applies inherited headers or certifies ownership, notes, taxonomy, units or position identity.

On the three already investigated headerless cases, CMG Holdco's Crescent table 36 is geometrically consistent with tables 35 and 37: all 16 cost and 16 FV facts align with the proposed columns and expected period/entity. MES Intermediate's Varagon table 55 remains unresolved because adjacent header fields are missing; Krayden's table 11 remains unresolved because adjacent headers/period support are missing and custom cost concepts are outside this diagnostic's mapping. Krayden's independently observed visible/context instrument conflict remains unresolved too.

This isolates a plausible reusable continuation mechanism in one consumed filing, not validated automatic support. Any implementation must retain the donor header's actual table/row coordinates separately from data-row boundaries in the receiving table, and independently establish schedule/ownership/notes continuity. Copying a header record into another table would misrepresent its provenance and can alter section-boundary handling. No such copy was applied.

Artifact: header_continuation_probe_972590ca4ffead8e.json. Seventeen focused tests pass, including column changes, merged cells, changed periods/entities, hidden evidence, custom concepts and a contradiction on a non-target row. All three frozen bundles retain their blocked status; the overall 39/28 split and API accounting are unchanged. This is an isolated diagnostic with no production changes.

## 2026-10-04: frozen later-period C104 transfer

Selected two of 35 Ares Strategic Income C104 flags for 2026-03-31, using the lowest deterministic salted row-ID hashes without replacement. Builder/runtime and input hashes were frozen before opening the later source. This is a familiar-filer, later-period offline probe, not an independent or new-filer holdout. No API calls were made.

Both selected cases remain blocked solely by missing referenced note 13: Denali's revolving loan (ROW-a5dcb49c5296d21a, source t18r33/context c-392) and SGP Shaka's warrant (ROW-0f8a9c553173fb19, t42r27/context c-1182). Each has three source sibling candidates. Direct local source extraction confirms tagged fixed-zero FV at both anchors, but this does not certify complete evidence, identity or a false-alarm disposition. Reference labels remain unassigned.

Note 13 is present after table 71, before comparative SOI table 72 (2025-12-31). The last dated table before the note is table 57 (2026-03-31, currency forwards); table 56 is a position schedule. Tables 58-71 contain swaps, affiliate movements and loan/equity commitments. The 14-table index gap from table 57 exceeds the builder's three-table association limit. An identically worded note 13 also follows comparative table 130; matching wording is not a basis for borrowing its scope. This reproduces the earlier Ares long-gap note limitation in another period, without widening the parser's limits or promoting readiness.

The core benchmark remains 67 flags / 11 funds / 26 filings / 39 ready. This separate arm adds two blocked flags and one filing: 69 selected numeric cases across the same 11 funds and 27 filings in total. The separate TCW source exploration adds one further filing outside those numeric cases. Only 42 unique natural flags have model calls; the 100-call budget remains exhausted. The 33 unsampled group members remain unreviewed; no parent-work savings are claimed.

Artifacts: later_period_availability_101f3a442774baad.json; later_period_c104_57/ (freeze, selection and replay); later_period_c104_source_58.json; missing_note_inspection_3cdc76304ddd12df.json. Source accession 0001628280-26-034133, SHA-256 170a2f9df529b38b369fdb66327c951847bc628a484aaf430ec0648e8468cb5d. Diagnostics completed directly with snapshot checks; no pytest, full suite, rebuild/export or production-writing semantic diff was run for these diagnostic-only additions.
