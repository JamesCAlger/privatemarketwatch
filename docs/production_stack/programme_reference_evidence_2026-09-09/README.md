# Programme reference and eligibility evidence

See [the assessment](../programme_reference_and_eligibility.md) for findings,
limits, reuse decisions and the next executable task. These files describe cached
inputs as inspected on 2026-09-09; they are not production outputs or acceptance
gold. Do not edit original labels, live thresholds or the active baseline to
make them agree with this bundle.

| Files | Purpose |
|---|---|
| `obligations.csv`, `eligibility_quarters.csv`, `eligibility_summary.json` | All 910 slots; eligibility, output presence and remaining uncertainty kept separate |
| `missing_output_obligations.csv` | All 131 original output gaps, with current dispositions |
| `lifecycle_decisions.csv`, `source_passages.json` | 32 reviewed lifecycle bounds and 39 exact source passages, hashes, normalization method and offsets |
| `companyfacts_evidence.csv`, `positive_investment_evidence.csv`, `companyfacts_concepts.csv` | Bounded fact inventory; positive investment evidence is not necessarily a primary fund-total anchor |
| `fund_metadata.csv`, `fund_source_documents.csv`, `xml_fallback_documents.csv`, `early_source_documents.csv` | Actual lifecycle source documents and metadata; BDC election is not automatically the investment start |
| `source_document_frame.csv`, `reference_pilot.csv`, `reference_summary.json` | 910 document-candidate slots and 61 calibration clusters; selection does not certify source coverage or resolve period/amendment precedence |
| `benchmark_inventory.json`, `existing_*_reference_index.csv` | Existing source-field, entity and position-match assets, review metadata and exposure caveats |
| `development_source_rows.json`, `development_expectations.json` | Raw source rows/inline facts/units/contexts and four development case definitions; not held-out truth |
| `all_input_manifest.csv`, `verification.json`, `artifact_manifest.json` | 2,083 pinned inputs, verification scope and archived artifact hashes |
| Seven `*.py` collectors | Cache-only reproduction logic; bounded timers, read caps and isolated output conventions |

Reproduction: copy the seven collectors to a fresh directory under
`scratch/YYYY-MM-DD_<topic>/` inside this repo. Run `inventory.py`, then
`xml_text_fallback.py`, `early_documents.py`, `benchmark_inventory.py`,
`adjudicate.py`, `reference_frame.py` and `development_examples.py` in that order.
The scripts write beside themselves, including disposable normalized source
texts. **Do not run them directly in this dated evidence directory.** Compare
input hashes before interpreting differences. They require the existing Python
environment's DuckDB and lxml; no installation or network preparation is included.

`development_expectations.json` is manually source-reviewed and must be copied
separately when reproducing the case package. It is not generated from pipeline
output. Lifecycle bounds in `adjudicate.py` are similarly reviewed decisions,
not a regex classifier to promote into production. The regexes locate evidence
for those decisions; failed matches stop the collector.

Full cached filings and normalized scratch texts are not copied into Git. Source
offsets refer to the recorded normalization method/text hash, not byte offsets
or verified viewer highlights. HTML DOM XPath and parser-specific gold table
indices can differ. A browser citation implementation must verify document,
period, row and field, including contradictory units and repeated numbers.

The initial assessment is [here](../programme_contract_assessment_2026-09-09.md).
Its canonical holdings hash is rechecked in `verification.json`; no rebuild or
refresh of production data occurred in this exercise.
