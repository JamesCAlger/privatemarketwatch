# Programme rule authority: inventory and runtime assessment

Subsequent update: [overnight closeout](programme_spec_closeout_2026-09-09.md) measured all 22 admitted post-staging B2 applications on the frozen population, including pre/post fund-quarter effects and order replay. The full application audit contains 175 entries. Global/wrapper/cache/Layer-C interaction certification remains an implementation requirement; the fixture findings below remain valid at their stated scope.

Date: 2026-09-09. PREP-01 / P1 / SPEC-RULES. Status: **source trace and ten bounded runtime replays complete; full rule-instance certification and PREP-01 remain open.** No production behavior changed.

The architecture needs one admitted rule plan shared by verification and production, followed by one final writer. The current implementation does not enforce those boundaries. This assessment reproduces ordering, admission, audit and artifact defects on small fixtures and identifies the existing rules that the implementation packages must account for. These are engineering requirements under the resolved decisions; no new financial policy choice is needed to record them.

## Evidence and limits

The [durable run](programme_rule_evidence_2026-09-09/README.md) ran from **19:41:11 to 19:41:21 UTC**, at dirty working-tree HEAD `2e0491a45d1493e7a3ee329aee52ec96bb34986c`. It pins 879 input files, including source code, rule assets and selected lookup inputs. HEAD alone cannot reproduce the local changes. The [run summary](programme_rule_evidence_2026-09-09/run1/run_summary.json) records versions, metadata checks and completion; it does not attest a production release.

| Output | Coverage and interpretation |
|---|---|
| [Authority register](programme_rule_evidence_2026-09-09/run1/rule_authority_register.csv) | 77 rule families: current source/function and lines, reads/writes, selector/order, target disposition and implementation package. Families are semantic groups, not a count of atomic business rules. All named functions resolved. |
| [Configuration inventory](programme_rule_evidence_2026-09-09/run1/rule_assets.csv) | 740 assets with hashes, scope/selector data where available, loader eligibility, schema findings and current role. Extends the earlier 534-file inventory with 201 existing HTML templates and five retired conservation overrides. |
| [Wrapper sections](programme_rule_evidence_2026-09-09/run1/wrapper_sections.csv) | 1,307 section entries distinguish staging, dispatch and oracle/spec metadata. This is not proof that every section executes. |
| [Embedded source sites](programme_rule_evidence_2026-09-09/run1/embedded_code_sites.csv) | 2,212 Python branch and SQL source candidates in the registered modules. Includes technical control flow; needs semantic review before treating each site as a rule. |
| [Control inputs](programme_rule_evidence_2026-09-09/run1/control_inputs.csv) | 14 configured files inspected for presence, hash and bounded CSV count/schema or JSON shape. These inputs overlap the asset inventory; do not add the counts. |
| [Runtime observations](programme_rule_evidence_2026-09-09/run1/runtime_probes.json) | Ten isolated replays using synthetic frames of at most 20 rows. Demonstrates implementation behavior, not source correctness or cohort-wide financial impact. |

Three separate questions must remain separate: **can a loader admit this rule; does its selector match the intended rows; does its application produce a correct source-supported result?** This run measures the first, traces the second and probes selected interactions. It does not evaluate every selector on the 70-BDC history or replace the independent reference programme.

## What is actually available to the runtime

Counts below are from the live read-only loaders, not recursive directory counts.

| Family | Loaded / inspected state | Current authority |
|---|---|---|
| BDC wrappers | 78 assets; 77 v3; 76 dispatch specifications; 51 staging configurations | Separate consumers load dispatch and staging sections. Four identifier parsers, nine comma-delimited CIKs, 34 prefix-rule CIKs and 21 issuer-bridge rows also load. These counts overlap. |
| B2 corrections | 40 assets; **38 leaves loaded**, all passing the correction schema when separately checked | Runtime loader accepts dictionary JSON from its one-level path pattern without invoking that schema validator. Schema validity alone is not evidence of approval or correctness. |
| Layer C investigation rules | 151 assets; **137 leaves loaded** | Rules are schema-checked during application. One invalid dedup leaf was found in a pulled subdirectory outside the loader pattern; it is not an active invalid rule. |
| Independent anchors | 67 assets; **60 records loaded** | Requires a numeric total and supported explicit basis. Seven assets are not admitted by the observed shape/path checks. |
| HTML bridge | One asset; **32 rows loaded** | Source-key joins after staging; file naming alone does not separate proposed and admitted records. |
| Agent A grammar/anchor inputs | 70 grammars and 69 anchor assets | Grammar overlay is a diagnostic proposal lane. Saved `identifier_spread_corrections` are a separate production writer at S06. Do not describe every grammar as a production field rule. |
| Rate conventions | 42 assets | Convention/return-gate inputs, not a general staging coupon writer. |
| HTML templates | 201 version-3.0 assets | Requested by CIK by existing HTML extraction. File presence does not establish extraction quality or public-cohort coverage. |
| Fund highlights wrappers | **Zero loaded** | Existing loader supports concept choices, aliases, source preference and capped oracle tolerance. An empty configured framework contributes no wrapper coverage. |
| Retired conservation scope | Five files below `_retired/` | No current consumer found. Current published-basis sums use `published_basis.py`; do not resurrect historical numerator carve-outs. |

The source extractor is **`pipeline/bdc_filings.py`**, including cached extraction and dimensional deduplication. The earlier conflict table's `bdc_holdings.py` reference was incorrect and has been corrected.

Important saved inputs are also rule dependencies:

| Input | Observed state | Implication |
|---|---|---|
| Manual row corrections / aggregate-header flags | 9 / 1,978 rows | Explicit composite-key corrections and reviewed header vocabulary need separate admission and selector accounting. |
| Fund strategy candidates | 14,814 pinned rows; 14,678 live rows; reference has 621 rows | Pinned file exists and takes priority. The counts show distinct inputs, not necessarily contradictory decisions. Missing `fund_strategy_overrides.json` is a separate no-op control. |
| Company / label GICS caches | 184,708 / 2,502 rows | Different producers and subjects. Neither cache count measures supported classifications or unique current holdings. |
| Reviewed unclassified cache | 2,807 rows | Supplies conditional classifications and JV flags; flag assignment must be tracked separately from classification assignment. |
| Lien cache | Absent | The configured late-cache helper has no input in this snapshot. |
| Entity / identifier lookups | 141,796 / 105,167 rows | Saved join inputs can affect later rebuilds. Row counts do not certify unique join keys or correct identity. Entity override JSON also exists. |
| FX rates | Header only: zero rows | PREP-01's real conversion requirements and source/date recommendation remain unfinished. |
| Financial scale constant | CIK `0002012139`: multiplier 1,000 | Applied conditionally against positive amounts below the CIK's historical maximum divided by 100, with further cleaning afterward. This is a history-sensitive heuristic, not a document-unit attestation. |

## Reproduced interactions and required treatment

All numbers in this table are **fixture values**, not portfolio dollars. Full inputs, audit results and explicit stubs are saved in the runtime observations.

| Probe / finding | Observed behavior | Target requirement and package |
|---|---|---|
| **B2 order** | Two schema-valid leaves classify and deduplicate the same two-row frame. Production uses alphabetical fix-class order and retains one row/FV 100; verifier uses stage order and retains two rows/FV 200. | F05/F10/F12: one compiled plan, including tie/conflict handling, used by both paths. Structural/field dependencies must be explicit. WP-02. |
| **B2 scoped counterexamples** | A valid quarter-scoped rate fix changes only its CIK's BDC row. Other CIK, N-PORT and another quarter remain unchanged. | Preserve these protections while repairing admission/order. A global application shortcut is unacceptable. WP-02. |
| **B2 proposed payload** | A synthetic `.proposed.json` missing evidence, confidence and quarter scope loads despite nine schema errors and changes both fixture quarters. | F05: require schema, admitted decision/version and explicit scope before execution. Actual loaded production leaves passed the separate schema check; this probe demonstrates a boundary weakness, not an observed malformed production correction. WP-02. |
| **HTML proposed payload** | A schema-shaped `.proposed.json` loads. The loader does not validate the claimed source hash against a document. | F05/F09: admit versioned bridge decisions with source binding; reject unadmitted files regardless of location/name. Hash validation can occur in the admission stage, provided the build verifies that admitted identity. WP-02/03. |
| **Wrapper trial resolver** | `reload_wrapper_specs(trial_dir)` loads fixture dispatch, while `_load_staging_configs()` still reads the production directory and does not see fixture staging. | One pinned wrapper snapshot must reach every consumer. This proves staging changes are outside the current dispatch-overlay trial, not that the trial's supported dispatch changes fail. WP-02/03. |
| **GICS replacement** | Cache application changes a matched existing GICS value and clears an unmatched existing value to blank. | F11: define field authority and evidence per assignment; do not silently treat the company cache as blank-filling. The fixture does not establish which prior classification was correct. WP-02/07. |
| **Empty unified bundle** | Empty-input build writes CSV but no Parquet companion. | A successful stage needs a complete typed empty bundle, or an explicit incomplete/failed disposition; file presence is insufficient. WP-01. |
| **Isolated schema strictness** | A deliberately wrong-column canonical-name CSV outside production gets a default companion; explicit `strict=True` raises `OutputSchemaError`. | Candidate adapters must request strict schemas explicitly. Existing production-path defaults are a different case. WP-01. |
| **B2-only audit** | Real finalizer applies the fixture correction and writes CSV; no application-audit file is produced when raw exclusions and Layer C are absent. | F05: persist every enabled store's applications, including zero/no-op/error outcomes, and bind audit to the completed bundle. WP-02. |
| **B2 error finalizer** | A missing selector column returns an error audit; the finalizer still writes CSV and omits that audit file in the B2-only case. | An admitted rule execution error must block successful stage completion/sealing. Preserve failed candidate data and diagnostics for review without presenting them as a completed release. WP-01/02. |

The last two probes exercise actual B2 application and finalizer/writer flow with one pre-staged row. Source staging and unrelated late lookup/cache helpers are explicitly stubbed. They are boundary replays, not miniature full production rebuilds.

Other traced interactions remain candidates for population replay: manual correction then fund strategy then B2 then Layer C; classification stabilization followed by global restoration; company cache followed by real-estate fund GICS reassignment; transient selector row IDs followed by final row-ID allocation; and later entity/position writers rewriting canonical holdings. The existing [F01-F12 resolution](programme_conflict_resolution.md) remains the semantic disposition authority. These findings refine its evidence and packages rather than create twelve new owner decisions.

## Remaining work and handoff

1. Compile rule-instance records from the family/asset/section inventories, including current units, exact read/write sets, effective scope, decision identity and supersession. Review the embedded source candidates; not every technical branch is a business rule.
2. On a synchronized isolated cohort candidate, capture pre/post selection, changed rows/fields, no-ops, errors and overlapping selectors for each applicable rule. Compare verifier/production application events and explain financial deltas. Do this after WP-01 provides safe candidate paths; current defects must remain visible in the diagnostic result.
3. Finish source-unit and genuine FX needs by field/quarter, using the existing source cases. Resolve provider/date policy from demonstrated requirements. The empty rates file alone does not show how many values need conversion.
4. Continue PREP-02 independent rosters, labels and identity cases; then PREP-03 synchronized measurement/calibration. No current observation supplies a new numerical acceptance threshold.

**Readiness:** enough evidence to specify the bounded WP-01/02 control fixes; not a complete rule-instance certification or authorization to start unrestricted remediation. The implementation plan and SPEC-RULES status now link this run so future work can reuse it.

## Verification

Executed the named diagnostic in about ten seconds with a 240-second timeout, two DuckDB threads, a 1 GB limit per connection and no disk spilling. CSV controls were counted in DuckDB, not row-level Python loops. Socket connections and Python writes outside the evidence directory were blocked; inspected native DuckDB I/O was restricted to that directory. Fixtures and finalizer outputs stayed there.

Before/after size/mtime checks found **no drift in 341 current top-level output and recursive frontend-data files**; all 879 pinned inputs retained their size/mtime. This is not a full historical-tree content audit. An initial scratch attempt spent too long scanning the historical output tree and was stopped; the retained run uses the documented bounded metadata scope. Its fixture results and final status are complete.

After drafting, all **879 input SHA256 hashes were rechecked and matched**. Verified unique family/asset keys, inventory counts, all ten recorded observations, 108 local links across seven documents, balanced fences and whitespace. The handoff check is saved under `scratch/2026-09-09_programme_rules/verify.ps1`.

No pytest/full suite, frontend build, production rebuild/export, semantic baseline diff, reattestation, source download, enrichment call, gold/threshold edit, baseline refresh, production adoption or agent dispatch was run. Production code and data were unchanged. These diagnostics are development evidence; source accuracy and acceptance remain separate work.
