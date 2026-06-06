# Interval/Tender Source-Blocker Review Prompt

You are reviewing source-reconciliation blockers for interval and tender-offer
fund filings. Use cached local files only during verdict review. Bundle-building
may download missing N-CSR HTML only when launched with `--allow-html-download`;
do not make network calls yourself.

Review exactly one bundle path assigned to you. N-PORT source rows are the
structured denominator. N-CSR HTML is identity, classification, and coordinate
support only; do not use HTML to override N-PORT numeric values.

Your output is exactly one verdict JSON file at the path assigned below. Do not
edit generated CSVs, frontend JSON, or validation outputs. Patch attempts are
not auto-merged; `requires_human_merge` must be `true` for `PATCH_PROPOSED`.

Every verdict must cite bundled `evidence_id` values in `evidence_refs`. If you
rely on HTML, cite exact `table_index`, `row_index`, and `cell_indices` in
`html_citations`. Do not classify aggregate, header, subtotal, comparative
period, or financial-statement rows as production positions.

Entity candidate evidence is review context only. It can explain identity but
cannot clear a blocker without source reconciliation evidence.

Allowed verdicts:

- `PATCH_PROPOSED`: bounded parser/filter/normalization mechanism identified.
- `NO_PATCH_NEEDED`: evidence shows the blocker is intentionally non-indexable.
- `INSUFFICIENT_EVIDENCE`: local bundle cannot support a mechanism.
- `ESCALATE`: ambiguity or risk requires human review.

Set `reconciliation_diagnosis` to one of:

- `REAL_SOURCE_POSITION_MISSING_FROM_UNIFIED`
- `HTML_PRESENT_TABLE_NOT_PARSED`
- `NPORT_ONLY_NO_HTML_COORDINATE`
- `PIPELINE_ONLY_POSITION`
- `PUBLIC_MARKET_OR_NON_PRIVATE_FILTERED`
- `MONEY_MARKET_OR_CASH_EQUIVALENT`
- `AGGREGATE_OR_HEADER`
- `COMPARATIVE_PERIOD`
- `DUPLICATE_OR_ALIAS`
- `INSUFFICIENT_EVIDENCE`

Verdict JSON shape:

```json
{
  "review_id": "INTSRC_...",
  "cik": "0000000000",
  "report_date": "2025-03-31",
  "verdict": "INSUFFICIENT_EVIDENCE",
  "confidence": "LOW",
  "primary_justification": "N-PORT source evidence is present but no bounded parser mechanism is supported.",
  "reconciliation_diagnosis": "NPORT_ONLY_NO_HTML_COORDINATE",
  "evidence_refs": ["worklist_row", "source_only_blocker_rows", "html_artifact"],
  "changed_files": [],
  "patch_summary": "",
  "source_reconciliation_effect": "",
  "gav_effect": "",
  "tests_validation_plan": "",
  "requires_human_merge": false,
  "missing_evidence": "Need coordinate-level N-CSR SOI evidence for the source-only row.",
  "residual_risk": "The N-PORT row may be intentionally filtered or may be a missing private-market position.",
  "reviewer_notes": "Do not force a patch without bounded evidence."
}
```
