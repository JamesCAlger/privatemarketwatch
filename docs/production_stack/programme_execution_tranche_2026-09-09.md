# First programme execution tranche

2026-09-09. Proposed for owner approval, following the [specification closeout](programme_spec_closeout_2026-09-09.md). This document is a concrete execution offer; it does not authorize production adoption or alter D01-D13.

Review update, 2026-09-10: the owner supports the numerical recommendations as amendable working targets. Use the versioned amendment process in [measurement register section 11](programme_measurement_register.md#11-owner-review-and-amendable-working-targets-2026-09-10). Subsequent direction replaces the human reviewer appointment with [automated source verification](programme_spec_status.md#automated-reference-verification-no-human-label-prerequisite). This does not restart the expired tranche.

Execution and naming update, 2026-09-10: the owner subsequently started this tranche; it executed and stopped with verification incomplete. See the [handoff](programme_tranche_handoff_2026-09-10.md). The original proposal incorrectly called reference/measurement work "WP-02", which conflicts with the master implementation plan's rule-authority WP-02. T1 labels below identify this tranche's work without renumbering the master packages. No master WP-02 completion is implied. This document preserves the original execution offer and limits; it does not start a new window.

## End-state

In one bounded eight-hour tranche, deliver T1-RUNTIME's tested candidate boundary and T1-MEASUREMENT's versioned evaluator/reference inputs, plus a prioritized implementation queue tied to the measured failures. T1-RUNTIME contributes to master WP-01; T1-MEASUREMENT contributes to PREP-02/PREP-03 and the WP-11 evaluation framework. Deliver a candidate package ready for review even if its financial verdict remains FAIL or UNASSESSABLE. A failure must identify the missing evidence or mechanism; it must not be made to pass by weakening the gate.

Use the existing target contract, source crosswalk, 49-relation model, bronze/silver/gold processing design and physical/package plan. This tranche establishes the controls and measurement inputs for their implementation. The subsequent schema/rate/identity/dbt migration packages remain separately sequenced in the implementation plan.

## Fixed work

1. T1-RUNTIME (master WP-01 contribution): turn the preparation adapter into a supported candidate runner with mandatory stage manifests, strict required companions, complete dependency identities, rejection of mixed/stale artifacts, resume at completed stage boundaries and an explicit adoption boundary. Cover native-IO path restrictions with the selected execution environment; do not mistake the Python audit hook for an OS sandbox.
2. T1-MEASUREMENT (PREP-02/PREP-03 and WP-11 contribution): instantiate the versioned metric/reference schemas and the complete 28-criterion result inventory. Seed a new programme contract with the endorsed working targets, separate from the live quarter-acceptance gate; retain their calibration status and version. Support evidence-backed amendments with old/new results on the same candidate where meaningful. Every missing metric emits an explicit non-pass state.
3. Freeze the existing 61 packet dispositions and 20 label proposals as development evidence. Run an independent reference-review pass on the four complete small schedules and the source-label corrections before using them as final acceptance assets. Record author, reviewer, exposure, source hash, scope and disagreements.
4. Prepare four bounded remediation packets: 26North's untagged schedule, Golub's named cash instrument, Lord Abbett's missing schedule/dash handling, and the highest-impact source-backed identity/classification residual. Each includes one positive and one false-positive example, proposed rule home, expected row/FV/field changes and an unchanged-validation condition. Packet preparation does not require pretending that every mechanism is already resolved.
5. Run one integrated isolated candidate and the corresponding measurements. Present semantic changes against the frozen starting candidate; reconcile intentional changes to independent expected results. Preserve and explain the already existing differences against the official baseline.

Production data publication, baseline refresh, migration of the live financial convention and rewriting/promoting original gold are outside this tranche. Those actions require their concrete acceptance/adoption record. If approved work requires SEC downloads or paid research, stop that dependent packet and request the specific additional authority; continue independent work.

## Resource and work limits

| Unit | Hard limit | Basis |
|---|---|---|
| Entire tranche | 8 hours elapsed from recorded start; start no job that cannot fit its remaining allowance | Finite first implementation batch, not an open-ended rewrite |
| Concurrent heavy jobs | One rebuild, matching/identity job or full test suite at a time | Shared 24GB Windows workstation and existing no-overlap contract |
| Snapshot/restore verification | 10 minutes each; 12 GiB input snapshot cap; require >=100 GiB free disk before another candidate | Measured input snapshot 5.73 GiB; completed-result restore 2.18GB/6.52s |
| Unified build | 90 minutes; 12 GiB monitored private memory; DuckDB 4 threads/6GB per connection | Successful observed run 35.8 minutes/~9.23 GiB private |
| Entity/matching/IDs | 60 minutes; 12 GiB private; DuckDB 2 threads/4GB per connection | Observed worker ~9.5 minutes, peak ~6.34 GiB |
| PIK/evidence consumer build | 15 minutes; 12 GiB private | Observed status/proxy transforms roughly one minute including reads/writes |
| Bounded reference/diagnostic packet | 20 minutes of diagnostic runtime; <=120MB source document and <=1,000 extracted review rows per extraction job; larger scopes split explicitly | Existing literal-source tools and four small schedule examples |
| Browser scenarios | 4 minutes per declared workload; retain failed screenshots/log and target identity | 36 real local navigations measured, p95 3.91s |
| Focused tests | 15 minutes per affected package | Current 26 focused cases passed; fixture/setup cost included |
| Integration/full suite | 90 minutes reserved at handoff when shared contracts change; use required duration flags | No claim that the full suite was run in preparation; timeout is an incomplete verification, not a pass |
| Retries | One diagnosed execution retry per job; two distinct evidence/mechanism attempts per residual before escalation | Prevent repeated identical work and unbounded guessing |
| Paid external calls / SEC requests | Zero under this tranche unless separately authorized | Cached-source execution is sufficient for the fixed work above |

These are ceilings, not permission to spend every ceiling independently after the eight-hour total is reached. Reserve the last hour for integration, input-preservation checks, records and handoff. If shared-contract changes require the full suite, reserve its 90 minutes earlier. Finish fewer implementation changes with complete evidence rather than declaring unverified work complete.

Agent-token usage is not measured or capped by the preparation adapter. No token or dollar estimate is presented as measured. The runner must expose any available usage telemetry separately from CPU, memory and elapsed time. Bounded job/packet counts and durable results limit restart costs without assuming that a conversation or process survives a usage interruption.

## Checkpoint and recovery protocol

- Write the task ledger before execution: objective, approved scope, input/rule/reference identities, package dependencies, remaining time and current owned process IDs.
- At least every five active minutes, and after each material result, record findings, open hypotheses, next action and artifact paths. Preserve concise operational state that a fresh session can read without rediscovering the project.
- Write data into a new attempt directory. Flush/fsync files, verify required artifacts and hashes, then publish the completion manifest last. An `execution=complete` result can still have `quality=fail` or `unassessable`.
- On restart, verify the frozen input snapshot and each completed dependency. Reuse only the complete, valid stages. Never infer completion from file existence, a process exit alone or an old conversation summary.
- After a timeout/interruption, verify the owned worker has stopped. Retain the incomplete attempt and start a new attempt from the frozen inputs. A killed SQL statement is not resumable mid-query. Do not overlap a retry with its original process.
- A changed code/rule/input/reference fingerprint invalidates affected descendants. It does not invalidate independent completed source reviews whose own inputs are unchanged.
- Restore a release/candidate by content identity and verify all dependencies; adoption remains a separate explicit action. A failed candidate never replaces the last usable release.

## Stop and escalation rules

Stop the affected package for unexplained holdings/consumer changes, a signed-quarter regression, unknown accounting/currency/identity meaning, invalid acceptance evidence, required external authority or exceeded bounded attempts. Preserve the failed result and the tested hypotheses. Continue independent packages that do not depend on that decision.

Stop the tranche for attempted writes to protected production/reference/baseline assets, shared-resource overlap, missing input identity, failed isolation or exhaustion of its total allowance. Do not widen tolerance, silently discard troublesome funds, create source values, merge distinct tranches or relabel uncertainty to obtain a pass.

Any rule proposal must retain mechanism, exact source evidence, scope, confidence, before/after metric and residual risk. Put filer quirks in governed per-CIK rules unless a tested global mechanism is established. Validate changes against independent evidence before refactoring their implementation into dbt.

## Concrete handoff and owner decision

Deliver the versioned runner/evaluator changes, required tests, frozen reference proposal, four remediation packets, one integrated candidate result, explained semantic delta, runtime/usage ledger and concise unresolved-decision list. Append the project changelog and preserve all pre-existing user changes.

The owner authorized this tranche; it executed and stopped as recorded above. The former requirement to appoint an independent human reference reviewer is superseded by the automated reference protocol. Reference admission remains an implementation obligation; the current null authority and unapproved evidence are not converted into passes by that design decision. Routine reversible work within an authorized package should proceed without repeated permission requests; material changes to accepted risk require the documented amendment decision. This historical offer does not authorize another execution window.
