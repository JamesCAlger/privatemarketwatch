# V13 closeout rubric

Fixed 2026-09-28, before the V13 build starts. This document decides in
advance how V13's results are read, so that no finding after the build can
reopen a question this rubric has already answered. It executes the owner's
2026-09-14 clarification ("this is a refactor run, not a production run") and
the 2026-09-15 bounded-closeout authorisation.

## 1. Definition of closed

The refactor is closed when each package P1-P8 in `05_plan.md` has the
evidence file named in section 3 below, produced from candidate
`production-20260918-v13` (source sealed 2026-09-18,
`scratch/2026-09-16_refactor_continuation/v13-source-ready-v1.json`), and the
operational residual list in section 5 is recorded in the handoff.

Not conditions of closeout: production adoption, publication, baseline
refresh, threshold change, resolution of the 19 open owner decisions in
`05_plan.md` section 6, B1/B2 or enrichment campaigns, dbt migration. These
remain later owner and operational work.

## 2. Rules during closeout

1. **No source change.** No edit under `pipeline/`, `scripts/`, `tests/`,
   `schemas/`, `data/overrides/`, `data/reference/` until the handoff is
   written. Any such edit voids the V13 seal and restarts at the full suite
   (2h50m) plus a new seal; that is a V14, and this rubric does not authorise
   one. Findings go to section 5, not to code.
2. **One heavy job at a time.** The programme heavy lock scans for `pytest`,
   `rebuild_outputs.py` and `pipeline.programme.bootstrap`; none may run while
   a controller holds the lock.
3. **Evidence is recorded, never suppressed.** `candidate_footprint.py` runs
   without `--report-only`; its exit code is saved and adjudicated by
   section 4.
4. **Controllers only.** Every step runs through the named controller scripts
   in `scratch/2026-09-16_refactor_continuation/` (`build_v13.ps1`,
   `evaluate_v13.ps1`, `evaluate_v13_acceptance.ps1`,
   `task0_v13_public_chain.ps1`, `build_v13_twin.ps1`, `drills_v13.ps1`), each
   derived from its V12 counterpart with only candidate names changed, or new
   for twin and drills. Each writes `<sequence>/result.json`.

## 3. Evidence required per package

| Package | Refactor-done criterion (05_plan) | Evidence file(s) | Controller |
|---|---|---|---|
| P1 Finalizer and companions | companion_parity = 0, position_id_fill = 100%, two identical-input cold builds agree | `architecture-v13-sequence-v1/result.json` (five stages sealed; per-stage `verify_pair` metadata); `identity-v13-twin-v1/result.json` | build, twin |
| P2 Rule admission and validation | admission evidence recorded; legacy inputs reported | `retention-candidate-v13-v1`; `v13-overlay-review-v1`; unified-stage `agent_fix_application_audit.csv` verification | build, evaluate |
| P3 Public totals | public_partition_delta = 0; frontend build passes | `public-builds/production-v13-v1`; `architecture-v13-public-sequence-v1/result.json` (scope check, census, browser) | evaluate, public chain |
| P4 Gate extension | all collectors run; 13 quarter verdicts saved; UNASSESSABLE explicit | `source-v13-v1`, `e1-v13-v1`, `e2-v13-v1`, `e3-v13-v1`, `e4-v13-v1`, `p4-v13-v1`, `reattest-v13-v1`, `reattest-v13-versus-v11b-v1`, `quarter-deltas-v13-versus-v11b-v1.json` | evaluate, acceptance |
| P5 Enrichment integration | replay/admission verified; coverage reported | covered by P4 collectors and `delivery-v13-v1` coverage report; no new model calls | evaluate |
| P6 Atomic financial migration | contract cases pass; migration deltas explained | `financial-v13-v1` (vs t1-v5), `financial-v13-versus-v12-v1`, `financial-v13-versus-v11b-v1`, `v13-delta-diagnosis-v1` | evaluate |
| P7 Durable identity | identical IDs across two cold builds; exposed mg3 changes reviewed | `identity-v13-twin-v1/result.json`; `identity-v13-versus-v12-v1`, `identity-v13-versus-v11b-v1`, `identity-v13-original-v1` | build, twin |
| P8 History access and citations | accessible_holdings_difference = 0; evidence_path_or_unavailable = 1.0; misleading_links = 0; citation p95 <= 5000 ms | `delivery-v13-v1`, `delivery-browser-v13-v1`, `history-browser-v13-v1`, `repaired-history-browser-v13-v1` | public chain |
| F3 / F4 (04_acceptance) | cancellation, restore and completed-stage reuse on a fresh candidate | `v13-drills-sequence-v1/result.json` | drills |

Paths are relative to `scratch/2026-09-16_refactor_continuation/` unless they
name `scratch/2026-09-12_programme_e0/` artifacts (`identity-*`,
`financial-*`, `source-*`, `public-builds/*`, `architecture-v13-public-*`,
`*-browser-v13-v1`).

## 4. Pre-classified outcomes

Decided now. The build result is read against this table, not the reverse.

| Observation | Class | Basis | Effect on closeout |
|---|---|---|---|
| Footprint vs V12 flags `match_method.E_entity_fingerprint` contracting (54,435 toward ~5,300) | Expected | The tier E repair applies availability after ranking; V12's 10.2x growth was the defect | None. Record ratio. |
| Footprint vs V12 flags B2-leftover (or C/D/F) growing | Expected | Independent begin/end slots release rows V12 wrongly excluded | None. Record ratio. |
| Footprint: `labelled_parent_rows.0001803498` > 0 on V13 | **Implementation defect** | The separator rule predicts zero; a residual means a form was missed | Closeout blocked; V14 required. Stop and report. |
| Footprint: any other metric > 2x with no repair that predicts it | Implementation defect | Unexplained | Stop and report. |
| Identity vs V12: the Resideo and Metropolis packets improve; the two BCRED JV packets (MGP-4ea66bbd4ab5, MGP-d0dc3f51acd3) improve or hold | Expected | These are the three repairs' targets | None |
| Identity vs V12: IRI Group and Truck-Lite remain missed / false_split | **Operational** | Owner ruling 2026-09-17: joint-borrower identity is precision over recall; gold packets retained open | Listed in section 5 |
| Identity vs V12: any new regression | Review by packet, no code change | D08: gold may be wrong. Operational if attributable to a repair's intended effect or to a gold defect; implementation only if a code path misbehaves on the source facts | Attributed operational -> section 5. Implementation -> stop and report. |
| Twin: any row, ID or companion difference between V13 and its twin | **Implementation defect** | P1/P7 require zero | Stop and report. |
| P4: Q4-2025 `flagged_fv_share` FAIL (~10.7% vs 10%) | Operational | Attributed 2026-09-16 to FX conversions moving Bain / T. Rowe OHA across the band; economic tag correctness is data work | Listed in section 5 |
| P4: any quarter verdict FAIL or UNASSESSABLE on unadopted floors, missing evidence or source gaps | Operational | 2026-09-14 clarification | Listed with reason |
| Re-attestation vs signed-off quarters: any check REGRESSED | Review | Compare to `reattest-v12`... (not run) -> compare to V11b `p4-v11b-v2`. Attributed to a repair -> operational; otherwise implementation | Per attribution |
| F3 cancellation probe non-zero exit; F4 restore non-zero; F4 re-run does not print "Reused complete verified stage" | Implementation defect | Controls exist and are tested; a fresh-candidate failure is software | Stop and report |
| Public chain: build, scope, census or browser step fails | Implementation defect | P3/P8 | Stop and report |

## 5. Operational residuals carried into the handoff

Known before the build:

1. Tier B's own primary pass still excludes rows tier A claimed as an END
   (largest tier; lost recall, not wrong pairs).
2. Two joint-borrower gold packets (IRI Group, Truck-Lite) open by ruling.
3. Footprint gate's labelled-parent metric is an issuer_name proxy for a
   member-basis rule.
4. Q4-2025 flagged-FV share above 10% under FX conversion.
5. Economic currency-tag correctness against USD fund totals unresolved
   (Bain, T. Rowe OHA, Goldman, Phillip Street).
6. Lord Abbett parent-scope gap bridged by two uncovered Arkas facts and the
   SBLA parent interest; accounting membership preserves the distinction.
7. Golub Private Credit Q2-2023 cash-only quarter; MidCap Apollo Q4-2023
   positions exist only as later comparatives (policy decision pending).
8. 98 fund-quarters with no periodic filing; 26North FY2023 10-K without XBRL.
9. All 19 open owner decisions in `05_plan.md` section 6.

Anything the V13 sequence adds is appended here with its evidence path.

## 6. Sequence

| Step | Controller | Depends on | Budget (V12 actuals) |
|---|---|---|---|
| 1 | `build_v13.ps1` | seal | 5h24m stages + archives |
| 2 | `evaluate_v13.ps1` | 1 | ~1-2h |
| 3 | `evaluate_v13_acceptance.ps1` | 2 | ~1h (pair cache) |
| 4 | `task0_v13_public_chain.ps1` | 2 | ~1h |
| 5 | `build_v13_twin.ps1` | 1 | ~3h30m (unified + identity) |
| 6 | `drills_v13.ps1` | 1 (runs after 5 to avoid lock contention) | ~30m |
| 7 | Handoff: `2026-09-16_refactor_status.md` final checkpoint, `05_plan.md` status, changelog, memory | 1-6 | human |
| 8 | Merge `ensemble-fp-experiment` -> `main`, push; branch `filer-profile-pilot` rebased onto `main` | 7 | human |

Free space on C: at rubric time: 51 GiB (build requires 35 at start, 20 per
stage; archives release each completed working copy).

## 2026-09-29 ruling: V13 retired (owner, in session)
- V13 attempt 2 failed at the snapshot stage on a Codex CLI runtime delta (0.158.0). The owner ruled on 2026-09-29 that V13 is RETIRED, not deferred: no V14, the refactor build cadence ends, and the runtime ruling (pin back vs record a launcher-only deviation) is moot.
- Why: per the 2026-09-28 LAST-REBUILD rule a failed V13 pauses the refactor; the source seal is already void (pipeline/identifier_spread_corrections.py changed in e379e8a on 2026-09-29); the per-CIK issues these builds surfaced are absorbed by the filer-profile programme (docs/superpowers/specs/2026-09-29-filer-profile-programme-design.md on branch filer-profile-pilot).
- Consequence: the twelve matching repairs (91ef3cd..d6e5cce) stay unpublished until the first profile-era quarter build (programme sub-project 4), which needs a fresh focused + full-suite verification. Candidate, tranche and scratch evidence directories stay as evidence; no controller is to be restarted.
