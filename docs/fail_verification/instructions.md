# Codex FAIL Verification Instructions

Review exactly one evidence bundle at a time. Write exactly one verdict JSON to:

```text
data/output/fail_verification/verdicts/{verification_id}.json
```

Allowed actions:

- Read the assigned bundle and source artifacts referenced by the bundle.
- Compare values, dates, source rows, and nearby rows.
- Write the verdict JSON.

Forbidden actions:

- Edit pipeline code, generated CSVs, frontend JSON, docs, or schemas.
- Create sidecar notes or temporary scripts.
- Change validation thresholds.
- Suppress a rule because it is inconvenient.
- Claim high confidence without evidence references.
- Use "we ruled out one alternative" as proof of a positive verdict.

Verdicts:

- `CONFIRMED_DATA_ERROR`: the validator found unsafe output.
- `CONFIRMED_VALID_EXCEPTION`: the condition is real but explainable.
- `VALIDATOR_FALSE_POSITIVE`: the validator or comparison source is wrong.
- `INSUFFICIENT_EVIDENCE`: the bundle cannot support a defensible conclusion.

The anti-sycophancy check must state the strongest alternative explanation and
why it was rejected or left unresolved.

## Epistemic Contract

Every verdict must separate positive evidence from ruled-out alternatives.

Use `epistemic_assessment.confirmed_mechanism` to state what mechanism is
actually supported by the bundle. For every verdict except
`INSUFFICIENT_EVIDENCE`, this must name a positive mechanism and cite the
evidence IDs that support it.

Use `epistemic_assessment.ruled_out_alternatives` only for explanations that
were considered and rejected. Ruling out an alternative is not proof of the
chosen verdict.

If the bundle supports only negative conclusions, such as "this is not a broad
scale mismatch," but does not prove the actual mechanism, use
`INSUFFICIENT_EVIDENCE`.

Confidence caps:

- `ABSENCE_OF_CONTRARY_EVIDENCE` cannot support a positive verdict.
- `CORROBORATED_INFERENCE` cannot support `high` confidence.
- `DETERMINISTIC_RECONCILIATION` needs at least two evidence references.
- `INSUFFICIENT_EVIDENCE` must list the missing evidence.
