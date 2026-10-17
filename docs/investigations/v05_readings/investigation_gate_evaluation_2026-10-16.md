# Investigation gate evaluation - 2026-10-16

Owner requested enforcement, tests and evaluation after comparison with Claude Code's fund reviews.
This changes operator acceptance, not financial rules, published holdings or historical sign-offs.

## Implemented contract

- Every current outstanding ledger review_id needs structured affected/reviewed coverage, source
  evidence, conclusion, tested hypotheses and next action. A proposal does not waive investigation.
- Every observation needs a detection decision; detector proposals need a concrete suggested check.
- Every verification request distinguishes verification bugs from acceptance changes and carries evidence.
- A separate reviewer covers every finding, observation and request. Finding reviews attest to scope
  and source comparison. The digest binds the report, full outstanding ledger records and applicable
  proposal entries. Changed evidence, state or proposals invalidate review.
- Both investigator and reviewer quotes are checked against cached filing text. The validator itself
  is forbidden to fund agents. Missing review, missing evidence, rejected conclusions or incomplete
  coverage produce INVESTIGATION_INCOMPLETE (exit 4); they cannot enter the accepted-sandbox path.
- The 20-row random sample remains separate. Six builds limits repairs, not source reading.

## Actual report replay

Read-only audit using existing reports and sandbox ledgers; no report migration, fabricated evidence,
new source certification, data rebuild or overwrite of legacy gate files.

| Fund | Sandbox | Outstanding IDs requiring review | Result |
|---|---|---:|---|
| VISTA | viya | 14 | INVESTIGATION_INCOMPLETE |
| Goldman PMMC II | gpyf | 38 | INVESTIGATION_INCOMPLETE |
| Crescent | ccye | 53 | INVESTIGATION_INCOMPLETE |

All lack the new structured investigation/review contract. These are **not** counts of proven errors
or unread findings. Independent report inspection adds substantive evidence:

- Goldman: all 11 uncovered ledger parks repeat generic explanations. Some specifics exist elsewhere,
  but they do not establish complete coverage. The separate Diligent observation is more specific.
- Crescent: eight explicitly unfinished groups (seven X02 groups plus historical HTML). Three other
  groups describe rate contradictions; two findings concern one omitted Painters position. More
  specific documentation than Goldman, but still not complete investigation.
- VISTA: schema/review deficiency alone does not prove its substantive investigation was inadequate.

Exact audit output: scratch/2026-10-16_investigation_gate/evaluation.json. Reproduce with
`python scripts/v05_evidence/fund_gate.py investigation --label gpyf --cik 0001772704 --report docs/investigations/v05_readings/reports/0001772704.json`.

## Evaluation limits

Validation: 66 focused gate/contract tests passed in 56.32 seconds, including production-output
protection. Skill quick_validate passed. Independent code review found and prompted fixes for
validator-file protection, proposal digest binding, request evidence checks and detector specificity;
a second review found no further material validator bug. A forward workflow review correctly stopped
Crescent from advancing and required completion of the explicitly unfinished groups.

Full pytest, data rebuild and re-attestation were not run. The full semantic-diff backstop previously
timed out in this session after ten minutes without a verdict; it was not repeated for this
operator-only change. Existing unrelated dirty data artifacts were preserved.

Machine checks prove required structure, exact finding identity coverage, digest freshness and quote
existence. They cannot prove an honest affected-row manifest, correct financial interpretation,
actual reviewer independence or useful detector performance. These remain explicit independent-review
responsibilities. True independence is established by orchestrator dispatch, not a JSON name.
Legacy reports must be investigated, not merely padded with fields. No claim is made that Codex now
outperforms Claude Code; the new contract blocks the demonstrated premature-acceptance route.

No SEC downloads, production artifact writes, threshold changes or new disposition acceptances.
