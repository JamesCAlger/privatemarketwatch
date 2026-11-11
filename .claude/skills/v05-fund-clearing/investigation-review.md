# Investigation and independent review contract

Investigation completeness is separate from data correctness and repair completeness. Every
outstanding ledger `review_id`, including findings covered by proposals, needs an investigation.
Use the exact ID as `finding_id`; never recompute date hashes. No grandfathering of old reports.

The report carries `investigator_id` (actual agent identity) and `investigations` entries:

```json
{
  "finding_id": "<ledger review_id>",
  "coverage": {
    "affected_rows": ["<accession/context/row-id or fund-quarter-metric key>"],
    "reviewed_rows": ["<same stable keys, only those actually checked>"]
  },
  "evidence": [{"accession": "<filing accession>", "text": "<verbatim printed line>"}],
  "conclusion": "confirmed_error",
  "hypotheses_tested": ["<mechanism tested and observed result>"],
  "next_action": "<specific repair, proposal, evidence request or owner decision>"
}
```

Conclusions: `confirmed_error`, `source_ambiguity`, `false_alarm`, `insufficient_evidence`.
For insufficient evidence, include `missing_evidence`; this remains investigation incomplete.
For fund-level findings, coverage uses fund-quarter-metric keys; do not invent position rows.
An empty affected-row list is not proof that no rows are affected. Explain source-only/missing rows
using source context IDs. Compare affected coverage with the rule's actual flagged population.

Every observation retains its existing `observation_key` and adds:
`detection_decision: {action, rationale, reference}`. Actions are `propose_detector`,
`existing_detector`, `not_feasible`; existing_detector needs a rule or proposal reference.
Proposed detectors need a concrete suggested_check in the existing observation. Fixing a row does
not remove the requirement to consider recurrence. New rules are proposals, not automatically approved.

Every `orchestrator_requests` entry adds a unique `request_id`, `classification` (`verification_bug` or
`acceptance_change`), `evidence` (accession/text quotes), and `next_action`. The orchestrator must
record its response. A verification fix needs a test proving source-backed values pass and wrong
values fail. An acceptance change goes to the owner without silently weakening a check.

## Independent reviewer brief

The orchestrator supplies the final report, sandbox label, CIK and output review path. Read the
ledger and cached sources independently; write ONLY the separate review JSON. Do not edit the
fund report, fixes, gate or ledger. Use your actual agent identity, distinct from the investigator.

Carried entries (owner scope 2026-11-10): an investigation marked `carried_from` was not re-read
by the investigator. Verify that (a) the carried source exists and was supported by an earlier
independent review or is otherwise a recorded review, and (b) the finding's currently flagged rows
equal the carried `affected_rows`. Reject it if either fails. Verdict retirements the investigator
wrote under the owner's standing rule (`data/overrides/verdict_retirements/`) are checked by
re-running each entry's check and reading cited rows on the page; name any that fails.

Review every outstanding finding, not just parked entries. Reconstruct the flagged population
from rule output and compare it with affected_rows. Check every row claimed reviewed against the
cited source. Test the reasoning, hypotheses and next action. Read every observation and assess
whether its detection decision would catch recurrence without unacceptable false positives.
Reject generic explanations, unverified coverage, unsupported proposals and circular verification.
Missing evidence is a legitimate outcome; do not manufacture approval to finish the run.

Write this separate artifact (never embed approval in the investigator's report):

```json
{
  "reviewer_id": "<actual independent agent identity>",
  "report_digest": "<digest below>",
  "finding_reviews": [{
    "finding_id": "<ledger review_id>", "outcome": "supported",
    "coverage_verified": true, "source_comparison_verified": true,
    "rationale": "<why coverage and conclusion are supported; cite row keys>",
    "evidence": [{"accession": "<accession>", "text": "<verbatim line>"}]
  }],
  "observation_reviews": [{
    "observation_key": "<existing observation key>", "outcome": "supported",
    "rationale": "<independent assessment of evidence and detector decision>",
    "evidence": [{"accession": "<accession>", "text": "<verbatim line>"}]
  }],
  "request_reviews": [{
    "request_id": "<request id>", "outcome": "supported",
    "rationale": "<independent assessment of verification bug versus acceptance change>",
    "evidence": [{"accession": "<accession>", "text": "<verbatim line>"}]
  }]
}
```

Use `rejected` when unsupported. Compute the digest with
`investigation_review.report_digest(report, fund_gate.outstanding_findings(label, cik))` in a
named scratch script (no inline Python). Any report or outstanding-ledger change invalidates it.
Then run `fund_gate.py investigation --label LABEL --cik CIK --report REPORT --review REVIEW`.
The digest includes full outstanding ledger records and applicable proposal text. The audit is
read-only and exits 4 for incomplete investigation. The full `check` command also
enforces it. An actual separate reviewer is an orchestrator responsibility: a different name in
JSON cannot prove independence, and matching quotes cannot prove sound reasoning.

The original 20-row random page sample is still required. Complete it before final review, or
repeat the review after any resulting report/ledger change. Save incomplete reports and exact
remaining work; do not register acceptance or advance to another fund until this gate completes.
