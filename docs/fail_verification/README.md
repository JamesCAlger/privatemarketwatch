# FAIL Verification Harness

This workflow verifies open validation `FAIL` rows without changing pipeline
code or generated source datasets. The only agent-authored record is a verdict
JSON under `data/output/fail_verification/verdicts/`.

V1 scope is limited to `C101`, `X06`, `X09`, `C402`, `GAV_BDC01`,
and scoped N-PORT GAV coverage review under `GAV_NPORT01`.

## Commands

```powershell
python scripts/fail_verification/build_sample_manifest.py --dataset holdings
python scripts/fail_verification/build_sample_manifest.py --dataset funds
python scripts/fail_verification/build_evidence_bundle.py --dataset funds --all --overwrite
python scripts/fail_verification/build_evidence_bundle.py --verification-id <id>
python scripts/fail_verification/validate_verdict.py --all --dataset funds
python scripts/fail_verification/validate_verdict.py --verdict data/output/fail_verification/verdicts/<id>.json
python scripts/fail_verification/summarize_verdicts.py --dataset funds
```

Use `--all` on `build_evidence_bundle.py` only when the source-file hashing
cost is acceptable.

## Contract

- Use cached files only.
- Do not edit pipeline code, validation CSVs, generated frontend JSON, docs, or
  schemas during a verification run.
- Do not treat a lower FAIL count as success.
- If the bundle lacks evidence for a defensible conclusion, use
  `INSUFFICIENT_EVIDENCE`.
- High-confidence verdicts require cited evidence and human review before any
  remediation plan.
- Positive verdicts require a positive confirmed mechanism. Absence of contrary
  evidence is not enough.
