# Programme units, FX and identity migration contract

2026-09-09. Technical completion of D06/D07/D11 and PREP-01. Applies to the target programme; it does not alter current holdings or approve new production corrections. Read with the target contract and physical architecture.

## Field units and currency

Resolve each monetary field separately. Principal currency is not evidence that the same row's reported cost or fair value uses that currency. Retain the literal value, scale, sign, unit token, namespace-qualified measure, document hash, context, printed cell and table notes. Resolve opaque unit IDs within their own source document. The existing pipeline sometimes uppercases IDs: a case-insensitive bridge is allowed only when all matching original definitions agree. A token spelling such as `U_GBP` is not an ISO measure by itself. Reject composite/nonmonetary measures for monetary fields.

Evidence order: explicit field/cell denomination and applicable schedule notes; coherent source unit definition; inherited table/report denomination; finally the accepted USD assumption where no contrary evidence exists. A printed/tagged disagreement becomes a source-conflict decision with both observations retained. It is not resolved by this precedence mechanically when the applicable note, scope or column is unclear. Defaulted USD is labeled `assumed_USD`, distinct from reported or corrected USD. Invalid and unresolved values are not missing disclosures and cannot receive a missing-cost proxy.

The inventory examined 796 accession groups, read 779 cached XML documents and found 17 unavailable XML groups. Case-normalized resolution identifies 6,650 foreign-tagged FV/cost/principal observations and 7,107 unresolved/missing-unit observations. These are field observations, not distinct investments or confirmed FX requirements. In particular, source tags can be wrong. The full counts by currency, field and quarter are retained in the closeout evidence. No foreign amount may enter a USD sum merely because the original CSV called it fair value.

Concrete source counterexamples:

| Source | Observation and required treatment |
|---|---|
| Apollo Debt Solutions, March 2026, accession 0001193125-26-215667, Forterro SARON term loan | Printed principal CHF 4.430m; cost 4.721m and FV 5.388m have AFN tags. Resolve the USD cost/FV presentation independently of principal. Never convert the AFN-tagged amounts automatically. |
| Same source, Forterro STIBOR term loan | Printed principal SEK 35.658m; cost 3.344m and FV 3.663m have RSD tags. These are a separate facility and field-specific conflict, not a global RSD rule. |
| Antares, September 2025, accession 0001193125-25-280627, BigTime Software | Principal cell explicitly prints $200 thousand while its inline unit is EGP: source-grounded USD correction proposal. |
| Antares, March 2026, accession 0001193125-26-221684, Riser Interco | Principal explicitly prints GBP981 thousand while its inline unit is EGP: source-grounded GBP correction proposal. This is a false-positive counterexample to replacing all EGP tags with USD. |
| Apollo, June 2024, accession 0000950170-24-094137, Delivery Hero | Principal prints Korean won and is tagged KPW. The contemporaneous note says Korean won without specifying South/North; later source text specifies South Korean won. Preserve this distinction: the later note corroborates a KRW interpretation but does not itself certify the older disclosure. |

The exact cached paths, SHA-256 hashes, contexts, row locators, printed values and tags are in `programme_closeout_evidence_2026-09-09/currency_cases/`. These are development references and correction proposals; no original gold label is overwritten.

## FX policy

Use a reported USD equivalent when the filing provides one for the same observation. Keep foreign principal in its original currency and expose a separately labeled USD analytical equivalent. For a genuinely foreign FV without a reported USD equivalent, convert only after unit adjudication. For foreign reported cost, retain the original accounting cost; a period-end USD translation is an analytical conversion and must not claim to reconstruct the filer's historical USD acquisition cost.

The default provider is the ECB euro reference-rate series. For a stock balance dated D, use the latest available observation dated on or before D, at most seven calendar days old. Use both legs from the same provider observation: `USD amount = original amount * USD_per_EUR / source_currency_per_EUR`; EUR's source leg is exactly 1. Record provider, observation date, publication/vintage identity, retrieval time, input hash and arithmetic version. No future-rate lookahead, mixed-date crosses, interpolation, inverse-direction guess, or silent rounding before aggregation. Decimal arithmetic is mandatory; display rounding is a consumer concern.

The ECB publishes reference rates on working days and quotes currencies against the euro. These rates are informational, which fits a labeled analytical translation rather than an execution-price claim. See [ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) and [ECB exchange-rate methodology](https://data.ecb.europa.eu/methodology/exchange-rates).

If a supported currency's rate is missing/stale, or the currency is unsupported, emit `FX_unavailable`/`FX_stale`; preserve the original amount and count its unassessable exposure. A source-reported equivalent or separately reviewed public-source quote can resolve it with an explicit provider decision. Do not invent an average or assume a peg. Provider outages cannot silently replace the frozen vintage. A revision creates a new quote version and candidate. No FX observations were imported in this preparation; the reference implementation is tested with conspicuously synthetic quotes, not represented as measured market data.

### Test coverage clarified after owner review, 2026-09-10

Real cached filings were inspected for field denominations and printed/tagged currency conflicts. The conversion implementation itself was tested with synthetic quotes: arithmetic direction, same-date crosses, weekend/no-lookahead selection, signs/zero, missing/stale rates and duplicate observations. It has not been tested end to end with a frozen historical provider-rate dataset and real filing amounts.

Before deploying that conversion path, save and version real provider observations, resolve the selected filing fields' currencies independently, and check conversions against independently calculated expected results. Retain source amount/currency, quote/source identity, date-selection decision and output. The distinction is real-source interpretation evidence versus a still-pending historical-rate integration proof; no new rate import or FX rerun occurred in this review.

## Persistent identity migration

Identity allocation and matching quality are separate. Allocate a UUIDv5 from `(identity kind, governed scope, immutable creation-decision ID)` using a fixed programme namespace. An allocation decision is permanent, source-backed and idempotent; it is not a hash of a mutable issuer name, current row ordering or the complete evolving chain. Entity scope is global legal entity; position scope includes filer and consolidation scope. Parent/JV, term loan/revolver, debt/equity and separately disclosed lots stay separate until evidence explicitly says otherwise. Cross-filer common borrowers share an entity where supported, not a position.

Bootstrap from source observations in the frozen candidate. First map legacy rows to document/context/physical-row anchors. Preserve legacy IDs only as `(legacy build fingerprint, legacy ID)` aliases. A missing or ambiguous source bridge stays unresolved; never infer identity from an unqualified old PID. Import existing source-reviewed match decisions as governed decisions with original evidence and benchmark-exposure metadata. Newly inferred matches remain provisional until their decision policy admits them. This permits migration without claiming that reproducible identifiers prove correct matching.

Reordering or adding observations does not change an allocated ID. Restatements/amendments get new observation anchors and explicit source-selection edges; an evidenced same instrument can retain its position ID. A split creates new identities and explicit reassignment history. A merge names one survivor and retires the other only when no current assignment still points to it. No silent merges, automatic reassignment or reuse of retired IDs. Persist allocations, assignments, aliases, decisions and supersession events in the same candidate/release snapshot. Restore must validate all their hashes before reuse.

Missing analytical cost uses the earliest selected, source-valid USD FV within an established same position and scope. A reported cost of zero wins; a valid zero FV donor remains zero. Multiple earliest donors are an ambiguity, even when equal, until selection resolves their source relationship. Invalid reported cost or unresolved FX is not absence. Store donor observation/date and method `first_observed_FV_proxy`; it is not reported principal, original contractual principal or reported cost. Historical latest-best views may expose a later first-observed donor; point-in-time consumers must filter by information availability separately.

`scripts/programme_closeout/identity.py` and `fx.py` are bounded reference implementations with counterexample tests, not production readers or a new matching algorithm. Production adoption is WP-03/WP-05 and requires the synchronized acceptance suite.
