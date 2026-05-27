# Position Match Rule Review Prompt

You are reviewing unmatched quarter-to-quarter position clusters.
Use cached local files only. Do not make network calls.

Review exactly one bundle path assigned to you. The bundle contains the
worklist row, unmatched residual rows, current/prior/later candidate holdings,
raw source rows where available, nearby accepted matches, existing position-id
edges, coverage context, artifact hashes, allowed patch scope, and required
validation commands.

Your output is exactly one verdict JSON file at the path assigned below. Do not
edit generated CSVs, frontend JSON, or validation outputs. Do not directly
approve production match pairs. Proposed rules are not auto-merged;
`requires_human_merge` must be `true` for `RULE_PROPOSED`.

Every verdict must cite bundled `evidence_id` values in `evidence_refs`.
Coverage improvement, row-count improvement, or GAV improvement is context only
and cannot be the primary justification. The primary mechanism must be
position-identity evidence from the bundle.

Allowed verdicts:

- `RULE_PROPOSED`: bounded deterministic rule identified. Include scope, rule
  type, deterministic conditions, positive examples, false-positive examples,
  guardrails, expected coverage effect, false-match risk, tests and validation
  plan, and residual risk.
- `NO_RULE_NEEDED`: evidence shows the residual should not be patched.
- `INSUFFICIENT_EVIDENCE`: local bundle cannot support a mechanism. State what
  evidence is missing.
- `ESCALATE`: ambiguity or risk requires human review. State the escalation
  reason and missing evidence.

Rules must preserve position-level semantics. Do not collapse distinct loan
tranches, preferred shares, warrants, equity co-investments, fund interests, or
other instruments into borrower-level matches. Proposed rules must specify
one-to-one enforcement, adjacent-quarter/span limits, and tranche/rate/FV
guardrails.

Verdict JSON shape:

```json
{
  "review_id": "POSMATCH_...",
  "source": "bdc",
  "cik": "0000000000",
  "quarter": "2025q2",
  "index_classification": "DIRECT_LENDING",
  "verdict": "RULE_PROPOSED",
  "confidence": "MEDIUM",
  "primary_justification": "Bundled source and candidate identity evidence supports ...",
  "evidence_refs": ["worklist_row", "match_residual_rows", "prior_candidate_holdings"],
  "changed_files": ["overrides/position_matching_rules.json", "tests/test_position_matching.py"],
  "rule_scope": "CIK/source/classification bounded scope ...",
  "rule_type": "tranche_key",
  "rule_summary": "Parse and compare ...",
  "deterministic_conditions": "Require ...",
  "positive_examples": [{"evidence_ref": "match_residual_rows", "reason": "..."}],
  "false_positive_examples": [{"evidence_ref": "prior_candidate_holdings", "reason": "..."}],
  "guardrails": "One-to-one adjacent-quarter matching with rate, maturity, principal, and FV guards.",
  "expected_coverage_effect": "Expected to improve short-span FV coverage for this CIK/class cluster only.",
  "false_match_risk": "Remaining risk ...",
  "tests_validation_plan": "pytest ...; python scripts/rebuild_outputs.py --returns; python scripts/rebuild_outputs.py --validate-rules",
  "requires_human_merge": true,
  "missing_evidence": "",
  "residual_risk": "Remaining uncertainty ...",
  "reviewer_notes": "..."
}
```
