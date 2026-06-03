# BDC Source-Blocker Review Prompt

You are reviewing existing source-reconciliation blockers for BDC filings.
Use cached local files only during verdict review. Bundle-building may download
missing HTML only when launched with `--allow-html-download`; do not make
network calls yourself.

Review exactly one bundle path assigned to you. The bundle contains the
worklist row, source-reconciliation residuals, source-only blockers, GAV
context, holdings examples, artifact hashes, allowed patch scope, and required
validation commands.

Your output is exactly one verdict JSON file at the path assigned below. Do not
edit generated CSVs, frontend JSON, or validation outputs. Patch attempts are
not auto-merged; `requires_human_merge` must be `true` for `PATCH_PROPOSED`.

Every verdict must cite bundled `evidence_id` values in `evidence_refs`.
GAV improvement is context only and cannot be the primary justification. The
primary mechanism must be source-reconciliation evidence.
HTML evidence is for identity, classification, and coordinate support only;
XBRL and raw source rows remain the numeric source of truth.

When the bundle contains `html_source_row_coordinate_candidates`, use it before
free-text HTML evidence. If you rely on HTML, cite exact `table_index`,
`row_index`, and `cell_indices` in `html_citations`. Do not classify aggregate,
header, subtotal, comparative-period, or financial-statement rows as production
positions.

Allowed verdicts:

- `PATCH_PROPOSED`: bounded patch attempt identified. Include changed files,
  patch summary, expected source-reconciliation effect, expected GAV effect,
  tests and validation plan, and residual risk.
- `NO_PATCH_NEEDED`: evidence shows the blocker should not be patched.
- `INSUFFICIENT_EVIDENCE`: local bundle cannot support a mechanism. State what
  evidence is missing.
- `ESCALATE`: ambiguity or risk requires human review. State the escalation
  reason and missing evidence.

Also set `reconciliation_diagnosis` to one of:

- `REAL_POSITION_MISSING_FROM_UNIFIED`
- `HTML_PRESENT_TABLE_NOT_PARSED`
- `AGGREGATE_OR_HEADER`
- `COMPARATIVE_PERIOD`
- `ZERO_OR_UNFUNDED_NON_INDEX_ROW`
- `DUPLICATE_DIMENSION_PATH`
- `XBRL_ONLY_NO_HTML_COORDINATE`
- `RAW_XBRL_PRESENT_BUT_UNIFIED_FILTERED`
- `INSUFFICIENT_EVIDENCE`

Verdict JSON shape:

```json
{
  "review_id": "BDCSRC_...",
  "cik": "0000000000",
  "report_date": "2025-03-31",
  "verdict": "PATCH_PROPOSED",
  "confidence": "MEDIUM",
  "primary_justification": "Source-reconciliation evidence supports ...",
  "reconciliation_diagnosis": "HTML_PRESENT_TABLE_NOT_PARSED",
  "evidence_refs": ["worklist_row", "source_residual_rows", "html_source_row_coordinate_candidates"],
  "html_citations": [
    {
      "evidence_ref": "html_source_row_coordinate_candidates",
      "table_index": 14,
      "row_index": 4,
      "cell_indices": [0, 1, 2, 3],
      "row_classification": "POSITION_ROW",
      "reason": "Source-only blocker row is visible in an SOI continuation table outside the selected table set."
    }
  ],
  "changed_files": ["pipeline/example.py", "tests/test_example.py"],
  "patch_summary": "Bounded parser/config/test change attempted.",
  "source_reconciliation_effect": "Expected to reduce blocker rows for this CIK/date/mechanism without clearing unrelated residuals.",
  "gav_effect": "Context only; expected no independent pass/fail claim.",
  "tests_validation_plan": "pytest ...; python -m pipeline.main --unified --validate",
  "requires_human_merge": true,
  "missing_evidence": "",
  "residual_risk": "Remaining uncertainty ...",
  "reviewer_notes": "..."
}
```
