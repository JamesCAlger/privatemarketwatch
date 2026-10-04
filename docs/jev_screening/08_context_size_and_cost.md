# Context size and inference cost

Measured 2026-10-04 on four already-consumed development cases. No additional
API calls, funds or production changes.

## Price and limits

The pinned `jev-1.13.0` model costs $0.042 per million input tokens, with free
output. Its limits are 64k tokens for the entire request and 32k for state plus
the longest question. State is ingested once. These are provider limits, not
the pilot's 22k whole-request proxy ceiling (tightened from 26k after comparing
estimates with observed usage). The proxy ceiling is not a context guarantee.
Source: [TypeSafe models](https://docs.typesafe.ai/models), checked 2026-10-04.

The session's 100 successful calls reported 1,580,960 input tokens. Applying that
published rate gives **$0.0664 estimated inference cost**. This is not an invoice
and excludes engineering, evidence review and B1 time. No B1 savings have been
demonstrated. At the same rate, 10k input tokens cost $0.00042; 30k cost $0.00126.

## Real-case offline sizing

Numbers below are rounded thousands of `cl100k_base` tokens for state only.
The provider uses its own tokenizer: these are sizing estimates, not confirmed
acceptance or billing counts. Longest questions add approximately 0.13-0.16k.

On the 12 current-builder API requests, actual input usage was 1.302-1.364 times
the runner's whole-JSON cl100k count. This ratio is not directly transferable to
the compact state-only counts below. In particular, the 24.8k Onex projection
must not be interpreted as a confirmed fit inside Jev's 32k constraint. Exact
provider tokenization or an actual bounded acceptance test would be required.

| Fund / period / example | Current bundle | Broad visible tables and notes | Broad structured tables, notes and contexts | All published columns | Visible tables plus selected published columns |
|---|---:|---:|---:|---:|---:|
| Fortress / 2026-03 / Exemplis | 8.2k | 17.5k | 210.3k | 97.1k | 39.0k |
| Onex / 2026-03 / Montana | 9.5k | 11.2k | 142.0k | 60.5k | 24.8k |
| Oaktree / 2025-12 / BioXcel | 10.8k | 34.3k | 250.5k | 211.3k | 70.1k |
| Monroe / 2026-03 / Premier | 13.1k | 99.1k | 912.5k | 538.2k | 183.7k |

Published quarter counts are respectively 141, 85, 385 and 923 rows. Selected
columns retain position identity, source context, cost provenance, amounts,
currencies, shares/principal, maturity and accounting scope. They are encoded
as one column list plus row arrays. This projection is not a complete contract
for every rule. All-column results use the same compact row-array encoding.

Literal whole-filing HTML is much larger: approximately 2.2-5.7 million estimated
tokens, including unrelated statements and hidden facts. It is not a useful
single-request payload.

The broad-table selection uses the existing parser's reporting date and cost/FV
headers. It is **not independently certified whole-SOI recall**. Tables may be
missed or included under unresolved scope. Visible text drops geometry and
XBRL identity/unit information; structured variants retain that evidence but
repeat substantial metadata. Neither variant has been classification-tested.

## Bundle decision and trade-offs

Use a shared, cached filing evidence store, then assemble each decision from the
target row, every plausible sibling, relevant headers, exact contexts and required
notes. Add rule-specific fields and provenance. Keep full source coordinates so
B1 can expand the investigation without a new download.

- Entire fund-quarter context avoids some retrieval decisions but exceeds the
  estimated usable context in three of four cases even with selected output
  columns. It also does not prove accounting scope or note completeness.
- Visible text is smaller but discards evidence needed for identity and units.
  It can support navigation; it cannot substitute for audited numeric evidence.
- Detailed structured evidence is reusable and inspectable but needs dictionary
  encoding and selective retrieval to fit. Lossless compaction alone previously
  saved only 3.57% on the tested request representation.
- Narrow bundles fit cheaply but require measured candidate recall and explicit
  fallback when period, scope, units or notes cannot be established.
- Shared state across multiple questions may reduce repeated ingestion, but
  sibling selection, per-flag decisions and audit accounting must remain separate.
  No multi-flag screening or production batching has been enabled.

The provider also reports that irrelevant context can reduce accuracy and
recommends filtering state; arithmetic remains better handled in code.
Source: [Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).

The practical constraint is evidence selection and validation, not inference
price. Adding all available data is neither generally feasible nor a replacement
for the bundle's evidence contract.

## Reproduction

Isolated script: `scripts/measure_jev_context_scope.py`.
Artifact: `data/pilot/jev_screening/20261003_shadow/context_scope_measurement_22.json`.
The earlier `_21` artifact preserves the initial all-column comparison. Four
fixed existing flags, cached sources capped at 40 MB, at most 5,000 published
rows per fund-quarter, bounded DuckDB memory and a 180-second watchdog. Source
and holdings hashes bind the measurement. No source downloads or model calls.

## Local bundle construction timing

A bounded measurement on four existing cases reproduced each frozen bundle with
an empty parser cache and again with its parsed filing reused. These are component
measurements on this machine, not service-level latency or a production benchmark.

| Existing case | Empty parser cache | Reused parser cache |
|---|---:|---:|
| Fortress Exemplis | 4.50s | 0.052s |
| Onex Montana | 4.19s | 0.039s |
| Oaktree BioXcel | 3.67s | 0.045s |
| Monroe Premier | 9.57s | 0.114s |

Artifact: `bundle_build_timing_40.json`, replay `superscript_notes_v4_39`.
All eight packets match their frozen fingerprints. Timing includes source
read/hash, parsing and evidence retrieval; it excludes CSV selection/join,
request preparation, model latency, B1 work and upkeep. OS file caches were not
flushed; one pair per case and a small overlapping read-only comparison limit
precision. Grouping flags by filing allows parser reuse, but maintenance and
independent review costs remain unmeasured. Do not convert these timings into
claimed B1 savings or extrapolate to the full cohort.

## Current ready-request sizing

Replay `note_formula_v4_48` has 39 evidence-ready requests. Using precisely the
runner's whole-request `cl100k_base` serialization proxy, sizes range from 5,782
to 25,355 tokens, median 11,060. Three exceed the 22,000 proxy cap:

| C107 row | Fund | Whole request proxy tokens |
|---|---|---:|
| ROW-502ef9ff97600955 | Ares | 22,361 |
| ROW-7f7d8d2bb7ebf851 | Ares | 24,464 |
| ROW-96f4cdf3e1312b04 | Ares | 25,355 |

Thus 36 of the 67 selected flags meet both current evidence and size requirements.
The newly recovered Jackson Paper bundle uses 6,906 proxy tokens; newly recovered
Spotless is the first oversized request above. The full 39-request proxy sum is
467,757, but it is not a provider-token estimate or billable usage. No API calls
were made. Provider acceptance is untested for these revised requests.

Artifact: `request_size_profile_ab836bcd37fdc6f6.json`. Exact bundle/request hashes
are recorded. A future size reduction must preserve geometry, required notes,
sibling coverage and contradictions; increasing the cap or truncating evidence
does not establish that a request is safe or fits the provider limit.

## Optional lossless encoding experiment (not enabled)

Component sizing shows source notes account for 15,953-17,352 proxy tokens in the
three oversized requests. Their full continuation tables retain many blank cells.
The earlier optional v1 encoding mainly addressed candidate contexts and cells
with inline facts; it left three-field cells and note tables unchanged.

The optional `lossless-grid.v2` experiment encodes ordinary cells as
`[column, span, text]`, or `[column, span, text, inline_facts]` when that key exists.
It also applies the encoding inside note continuation tables. Cells with additional
annotations stay as dictionaries. Every blank cell, row, note, fact and candidate
is retained; empty/missing/null fields stay distinct. The decoder reproduces the
original request exactly for all 39 ready cases. No runner setting changed.

| Representation | Total proxy tokens, 39 requests | Largest request | Above 22,000 cap |
|---|---:|---:|---:|
| Current runner | 467,757 | 25,355 | 3 |
| Optional v1 | 455,888 | 24,950 | 3 |
| Optional v2 | 420,709 | 20,236 | 0 |

The three Ares requests would fall to 17,896, 19,528 and 20,236 proxy tokens.
This is about a 10.1% aggregate proxy reduction, not measured provider savings.
Reconstruction establishes information preservation, not equal model attention,
confidence or accuracy. Earlier presentation sensitivity makes that distinction
material. All three remain size fallbacks under the unchanged runner.

Artifact: `replay_compaction_ff58d248ca734a0b.json`; component sizing:
`request_size_profile_04c78bc1f4760705.json`. Eleven focused compaction tests pass,
including malformed arrays, unknown encoding, additional cell annotations,
empty/missing/null distinctions and unchanged v1 behavior. No API calls.

Before enabling v2, freeze paired original/encoded requests and independently
reviewed references, include real-error controls and note-sensitive decisions,
and compare source choices, label errors, abstentions and routing disagreements.
Do not reuse old scores or choose the representation with the more convenient
confidence. Provider token fit also needs direct measurement under a new budget.

## Current builder timing (replay 52)

One empty/reused parser-cache pair per existing case reproduces each frozen packet exactly:

| Existing filing case | Empty parser cache | Reused parser cache |
|---|---:|---:|
| Fortress | 5.156 s | 0.045 s |
| Onex | 4.543 s | 0.038 s |
| Oaktree | 4.387 s | 0.045 s |
| Monroe | 11.701 s | 0.111 s |

Artifact: bundle_build_timing_54.json. These are source read/hash/parse/retrieval timings on this machine, not cold operating-system-cache measurements or population latency. They exclude input selection, CSV joins, model calls, independent review and maintenance. The earlier replay-39 measurements are retained; different builder versions and single trials do not isolate the cost of the hidden-content check. Reusing an already parsed filing is materially cheaper in these four pairs, supporting source-grouped processing within the bounded cache.

## 2026-10-04: supplementary disclosure appendix sizing

An offline sizing probe adds every additional row found by the optional published-name, exact-context and source issuer-column searches to the 39 currently ready requests. It preserves the existing candidates and excludes only already-present source coordinates. Thirty-one requests have additional rows. Other instruments, comparative periods and unknown table roles remain included; their relevance has not been independently audited.

| Hypothetical encoding | Aggregate cl100k proxy tokens | Maximum | Above 22,000 runner cap |
|---|---:|---:|---:|
| Existing request | 467,724 | 25,352 | 3 |
| Full navigation records | 571,389 | 26,157 | 4 |
| Locator index only | 509,149 | 25,741 | 3 |

Full records add 22.2% in aggregate; the locator index adds 8.9%. The index retains displayed cells, coordinates, role/period labels and context IDs but deliberately omits inline facts, unit/header evidence and context definitions. It is a navigation aid, not a substitute for full evidence. Neither option completes missing notes or proves identity/ownership.

Oaktree BioXcel X08, ROW-1c2a72c58fbc2d87, is the newly oversized request: 14 additional source rows take it from 13,657 to 24,360 proxy tokens; the locator version is 17,369. The related material includes other instruments and comparative disclosures. A source inventory should therefore support targeted, auditable evidence assembly; appending all name matches is not a demonstrated improvement in classification.

Artifact: disclosure_appendix_size_53f8f1a298625f47.json, produced by the isolated scripts/measure_jev_disclosure_appendix.py. No payload was submitted and the runner, bundle, readiness and routing contracts are unchanged. These are hypothetical serialized requests measured with cl100k, not Jev token counts, model outcomes or provider charges.
