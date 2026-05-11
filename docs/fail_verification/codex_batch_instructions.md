# Codex Batch FAIL Verification Instructions

You are reviewing sampled validation FAILs for the private markets holdings
pipeline. Your job is to produce verdict JSON files, not to fix code or data.

## Hard Rules

- Use cached local files only. Do not call SEC EDGAR or external websites.
- Do not edit pipeline code, schemas, docs, frontend files, or generated source
  CSVs.
- You may write only verdict JSONs under:

```text
data/output/fail_verification/verdicts/
```

- Do not create temporary scripts, sidecar notes, remediation files, or patched
  CSVs.
- If evidence is missing or ambiguous, use `INSUFFICIENT_EVIDENCE`.
- Do not treat “I ruled out one alternative” as proof of a positive verdict.
- Success is evidence quality and schema-valid verdicts, not reducing FAIL
  counts.

## Setup Commands

Run these from the repo root:

```powershell
python scripts/fail_verification/build_sample_manifest.py
python scripts/fail_verification/build_evidence_bundle.py --all --overwrite
```

The sampled worklist is:

```text
data/output/fail_verification/sample_manifest.csv
```

Evidence bundles are:

```text
data/output/fail_verification/bundles/{verification_id}.json
```

## Per-Bundle Loop

For each `verification_id` in `sample_manifest.csv`:

1. Open `data/output/fail_verification/bundles/{verification_id}.json`.
2. Review only the bundle and source artifacts referenced by the bundle.
3. Follow the relevant playbook in `docs/fail_verification/playbooks.md`.
4. Write exactly one verdict JSON to:

```text
data/output/fail_verification/verdicts/{verification_id}.json
```

5. Validate immediately:

```powershell
python scripts/fail_verification/validate_verdict.py --verdict data/output/fail_verification/verdicts/{verification_id}.json
```

6. If validation fails, fix the verdict JSON. Do not weaken schemas or validator
   logic.

## Verdict Rules

Use exactly one verdict:

- `CONFIRMED_DATA_ERROR`: output is unsafe and the validator correctly caught it.
- `CONFIRMED_VALID_EXCEPTION`: the condition is real but positively explained by
  source evidence or deterministic reconciliation.
- `VALIDATOR_FALSE_POSITIVE`: the validator or comparison source is wrong for
  this case.
- `INSUFFICIENT_EVIDENCE`: the bundle does not prove a defensible mechanism.

Every non-`INSUFFICIENT_EVIDENCE` verdict must have:

- a positive `epistemic_assessment.confirmed_mechanism.summary`
- `support_strength` other than `NONE`
- cited `confirmed_mechanism.evidence_refs`
- an `evidence_chain` tying each claim to an evidence ID in the bundle

`INSUFFICIENT_EVIDENCE` must have:

- `confirmed_mechanism.summary` as an empty string
- `support_strength` as `NONE`
- empty `confirmed_mechanism.evidence_refs`
- non-empty `missing_evidence`

Confidence caps:

- `ABSENCE_OF_CONTRARY_EVIDENCE` cannot support a positive verdict.
- `CORROBORATED_INFERENCE` cannot support `high` confidence.
- `DETERMINISTIC_RECONCILIATION` needs at least two confirmed evidence refs.

## Batch Validation

After all verdicts are written:

```powershell
$failed = 0
Get-ChildItem -File data/output/fail_verification/verdicts -Filter *.json |
  ForEach-Object {
    python scripts/fail_verification/validate_verdict.py --verdict $_.FullName
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
  }
exit $failed
```

Then summarize:

```powershell
python scripts/fail_verification/summarize_verdicts.py
```

## Stop Conditions

Stop and report instead of continuing if:

- bundle generation fails
- the same validation error repeats across multiple verdicts
- a bundle lacks the evidence needed for the rule family and this appears to be a
  harness defect rather than a case-specific `INSUFFICIENT_EVIDENCE`
- you find source/data mutation outside `data/output/fail_verification/verdicts/`

