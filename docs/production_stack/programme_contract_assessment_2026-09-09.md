# Contract-resolution assessment: saved artifacts

Assessment: 2026-09-09, 10:03:08-10:03:17 UTC. Git HEAD:
`2e0491a45d1493e7a3ee329aee52ec96bb34986c`, with existing local changes.

This is the measurement companion to the
[F01-F12 resolution](programme_conflict_resolution.md). It profiles the canonical
CSV and selected configuration stores without executing pipeline stages. It
prepares reproducible denominators and investigation worklists; it does not
certify source accuracy, eligibility, successful correction application or release
acceptance.

Evidence and reproducibility:
[results](programme_contract_evidence_2026-09-09/results.json),
[653 input hashes/stat records](programme_contract_evidence_2026-09-09/input_manifest.csv),
[queries](programme_contract_evidence_2026-09-09/queries.sql),
[collector and rerun instructions](programme_contract_evidence_2026-09-09/README.md).
All pinned inputs retained their size/mtime during the successful run. Hashes
identify the inputs read; this manifest is not a restorable release snapshot.

## 1. Required history: a denominator frame, not an eligibility verdict

The pinned 70-CIK cohort crossed with 13 required quarter ends creates **910**
fund-quarter obligation records. **779** have saved holdings; **131** do not.
Of those 131, **31** have at least one filing-index entry at the same report date.
The other 100 are not thereby proven ineligible: filing discovery, filing periods,
comparative disclosure, formation/operation dates and cache completeness still
require assessment. Likewise, a recorded local path has not been checked for
existence/content in this exercise.

Every record in the [obligation frame](programme_contract_evidence_2026-09-09/obligation_frame.csv)
therefore has `eligibility_not_yet_adjudicated`. Do not call 779/910 the final
coverage rate. A1's denominator must use the independently supported lifecycle
and disclosure obligations, including explicit unavailable evidence.

| Quarter | Funds with saved holdings | Saved holding rows | First-FV cost proxy rows |
|---|---:|---:|---:|
| 2023-03-31 | 39 | 9,440 | 283 |
| 2023-06-30 | 45 | 10,487 | 277 |
| 2023-09-30 | 52 | 12,511 | 223 |
| 2023-12-31 | 56 | 14,373 | 310 |
| 2024-03-31 | 59 | 16,306 | 432 |
| 2024-06-30 | 62 | 18,406 | 583 |
| 2024-09-30 | 63 | 20,174 | 736 |
| 2024-12-31 | 65 | 22,334 | 1,034 |
| 2025-03-31 | 66 | 24,395 | 1,204 |
| 2025-06-30 | 68 | 26,036 | 1,240 |
| 2025-09-30 | 68 | 28,146 | 1,286 |
| 2025-12-31 | 67 | 28,938 | 1,349 |
| 2026-03-31 | 69 | 30,067 | 1,425 |

Total: **261,613 observations**, not distinct investments. The
[quarter profile](programme_contract_evidence_2026-09-09/quarter_profile.csv)
also records signed/absolute FV, missing values, identities and classification
coverage. Dollar interpretation of mixed unresolved unit tokens remains a source
validation dependency; these are numerical sums of saved canonical values.

## 2. F01: confirmed spread-unit boundary defect in saved data

The Agent A correction store contains decimal-fraction payloads. Staging has
already normalized `basis_spread` to percentage points before this override runs.
`apply_spread_corrections` writes the decimal directly and its unit test expects
that decimal. No later global rescaling repairs it in unified holdings.

Exact CIK/date/identifier matching within the required cohort/history finds **10
saved rows**, all at CIK `0001633336`, whose spread equals the decimal payload
instead of the percentage-point equivalent. Their summed absolute FV across
observations is **20,780,000**, which is not a current-quarter exposure measure.
Two are in Q1-2026:

| Row | Saved spread | Correction's percentage-point equivalent | Saved FV |
|---|---:|---:|---:|
| `ROW-da375aab4d0ced10` | 0.0425 | 4.25 | 341,000 |
| `ROW-e10586bdd2e36ab1` | 0.055 | 5.50 | 3,117,000 |

This confirms a 100-fold unit mismatch relative to the correction's own meaning.
It does not independently certify the correction's source-value choice; the
implementation packet must recheck the cited disclosure. Unmatched correction
keys are retained in results: a missing exact match could reflect identifier drift,
scope or removed rows and is not proof that a correction never applied.

Separately, one loader-path-eligible all-PIK correction explicitly writes the cash
leg into `interest_rate` for Q4-2025. A pulled historical leaf also exists but is
outside the loader path. The active template must change with the all-in storage
and income migration; do not silently change its meaning in only one consumer.

## 3. F03: monetary unit worklist and conversion coverage

The extracted BDC CSV has **168 distinct field/unit-token groups** across the
required periods for FV, cost and principal. This includes missing units and
several spellings/opaque IDs for what may be the same monetary unit. This is a
unit-token inventory, not 168 currencies.

In Q1-2026, saved FV currency tokens include:

- 14,100 `USD`, 15,394 `U_USD`, 94 `UNIT_USD`, and 326
  `UNIT_STANDARD_USD_BVO0A1W2CK-D1RKEV3HOGW` rows.
- 39 blank tokens.
- 114 rows across `CAD`, `EUR`, `GBP`, `U_AFN`, `U_AUD`, `U_CAD`,
  `U_CHF`, `U_EUR`, `U_GBP`, `U_JPY` and `U_RSD`.

Resolve the unit IDs in the corresponding cached documents before deciding the
foreign-valuation conversion delta. Even a suggestive token is not a substitute
for its XBRL unit definition and field context. Unexpected source units may also
require checking whether the filer tagged the intended economic amount correctly.
Do not sum native amounts across those currencies as one economic exposure.

Q1 principal has **24,229** populated original amounts. **10,771** have populated
USD principal and status `source_usd`; **13,424** populated amounts carry
`missing_reference_fx`; another **34** have blank conversion status. The reference
FX CSV contains no data rows. The 13,424 count includes unresolved USD-looking
tokens, so it must not be reported as 13,424 foreign-currency loans.

SPEC-FX now has a concrete per-field/per-quarter inventory. Still required:
document-level unit resolution, actual non-USD requirements, pinned rate source/
date convention and source-backed conversion tests. No FX rates were invented or
fetched, and no new USD total is proposed from this token-only evidence.

## 4. F05: loader eligibility and correction ordering

The [instance ledger](programme_contract_evidence_2026-09-09/correction_instances.csv)
contains **251 JSON records** across four stores. It distinguishes paths the
current loaders can reach from nested/pulled paths they cannot reach. Non-JSON
support files explain some differences from the earlier file-level asset counts.

| Store | Loader-path eligible | Outside loader path |
|---|---:|---:|
| Anchor overrides | 67 | 0 |
| B2 corrections | 38 | 1 |
| Layer C investigation rules | 137 | 7 |
| Static HTML section bridges | 1 | 0 |

Path eligibility is only the first check: loaders or appliers can subsequently
reject schema, invalid basis, missing scope/columns, unsupported fix class, absent
rows or invalid predicates. These counts are not counts of verified or applied
rules. Selectors, scope, payload, hash and target disposition are retained for
each record.

The static bridge is
`data/overrides/bdc_xbrl_html_section_bridges/0001838126.proposed.json`. Its schema
matches the loader and all **41 records** contain the loader's required key
fields. `.proposed` does not prevent loading. This exercise did not establish
whether that file was separately approved, which records match current holdings,
or whether their source classification is correct.

Production B2's alphabetical ordering and verification's stage ordering differ
as algorithms. However, enumeration of the saved loader-eligible post-staging
leaves found **zero cross-stage order inversions within a CIK**. Thus there is no
measured current output error attributable to that ordering difference. It still
needs a shared order and an overlapping-rule regression case before future
promotions can rely on parity. Same-stage ordering and B2/Layer C interaction
also need runtime verification; this static test does not prove their equivalence.

The pinned fund-strategy candidate file exists. The configured
`data/output/lien_cache.csv` is absent, so that cache application is currently a
no-op; iXBRL and reviewed-classification inputs exist. Do not count every named
cache loader as an active mutator in this saved working state.

## 5. F02/F08/F11/F12: useful baselines and their limits

Q1-2026 observations:

| Measurement | Result | Interpretation |
|---|---:|---|
| Saved signed FV | 381,537,030,207 | Canonical numeric sum; no new currency certification |
| Saved absolute FV | 382,026,825,645 | Denominator for these absolute-FV coverage figures |
| Missing FV / negative FV rows | 0 / 3,957 | Negative FV is not automatically invalid |
| Cost proxy rows / reported output zeros | 1,425 / 0 | Zero output costs are currently replaced/nullified; source-zero audit still needed |
| Absolute FV on cost-proxy rows | 1,055,385,896 (0.2763%) | Proxy contribution coverage; no claim of correct donor identity |
| Populated coupon / missing coupon | 21,213 / 8,854 | No eligibility or source-accuracy conclusion from fill alone |
| Positive PIK with zero coupon | 14 | Candidates for cash/all-in interpretation checks, not automatic errors |
| GICS-filled rows | 15,041 (50.0249%) | Stored sub-industry present; sector correctness unmeasured |
| Absolute FV on GICS-filled rows | 278,818,887,009 (72.9841%) | Coverage only; not an accuracy score |
| Missing entity IDs | 860 | Populated assignments still need independent accuracy evaluation |
| Missing position IDs | 30,067 | All Q1 rows; matching results in other artifacts are not thereby disproven |
| Missing position keys | 5 | Filled keys are not proven stable or unique |
| Subsidiary-flagged rows | 66 | Numeric `is_subsidiary=1`; retained observations |

Across all 261,613 historical observations, `row_id` has **zero duplicate groups**
and `(CIK, quarter, accession, source context)` has **zero duplicate groups** among
nonempty keys. **159** rows use natural-key fallback; **261,454** use source
anchors. Every saved position ID is blank. This is not a rerun test, and does not
certify future collision handling or stability after source/value corrections.

Within `(CIK, quarter)`, nonempty `position_key` has **4,555 repeated-key groups**
with **5,459 excess members**. These may include legitimate separately disclosed
lots or ambiguous keys; they are a continuity/lot-discrimination worklist, not
permission to deduplicate holdings. The saved entity lookup has zero duplicate
`(issuer_name_variant, source)` join keys, including zero conflicting IDs on that
key. This excludes one present multiplicity problem, not semantic misresolution.

## 6. What this adds to acceptance preparation

Available now: pinned saved-input identities; all 910 obligation slots; thirteen
quarter profiles; field/unit/FX worklists; keyed spread counterexamples; correction
instance scopes and dispositions; loader/order findings; identity multiplicity
baselines; and explicit tests/consumers for each F finding.

Still unavailable: adjudicated obligation eligibility, independent complete
source rosters, full field-accuracy and inference benchmarks, gold-quality entity/
continuation/chain results, synchronized release repeatability and live browser
citation/performance results. No numerical approval recommendation is made from
fill rates, saved rule counts or this incomplete evidence frame.

Verification: bounded DuckDB/config collector completed successfully with a
240-second watchdog, two threads, 1 GB DuckDB memory limit and no disk spill.
Earlier collector attempts exited on SQL alias syntax errors; the completed run
supersedes their partial scratch outputs. No hidden collector remains. All outputs
were first written under session scratch and copied into this evidence bundle.
No pytest/build, source/correction replay, pipeline rebuild/export, semantic diff,
baseline change, reattestation, SEC download, enrichment call or fleet occurred.
