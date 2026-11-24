# Private Markets Data Platform — SEC XBRL Pipeline

The user has ADHD and requires a cocise communication style. Don't use mannered prose.

## Project Goal

Build a data platform for SEC-registered private markets vehicles (BDCs, interval funds, tender offer funds) with private markets indices derived from the data. The pipeline discovers all such vehicles, extracts investee-level portfolio holdings from their structured filings, and computes fund-level analytics, portfolio characteristics, and position-level indices.

**IMPORTANT: The indices are at the POSITION level -- each constituent is an individual loan or equity investment (e.g., "Acme Corp Senior Secured First Lien Term Loan"), NOT aggregated at the company/borrower level.** A single company may appear multiple times in the index if a fund holds multiple positions in it (e.g., a first lien term loan, a second lien term loan, and an equity co-invest are three separate index constituents). This mirrors how public credit indices like the Morningstar LSTA Leveraged Loan Index work: each loan tranche is a separate constituent, not rolled up to the issuer.

See `private_markets_index_spec.md` for the full specification including the four target indices.

## Scope: v0.5 (Current Working Scope)

Owner ruling 2026-10-05: work on a small sample before widening it. **v0.5 is the five largest cohort funds by 2026-03-31 fair value. All data-quality work, quarter sign-off and filer-profile work targets these five first.**

| CIK | Fund |
|---|---|
| 0001803498 | Blackstone Private Credit Fund (BCRED) |
| 0001812554 | Blue Owl Credit Income Corp. |
| 0001287750 | Ares Capital Corp |
| 0001838126 | HPS Corporate Lending Fund |
| 0001837532 | Apollo Debt Solutions BDC |

- **What v0.5 means:** these five are roughly half of cohort fair value. A quarter is signed off only when they have zero outstanding findings (see Quarter Acceptance Contract). The machine-readable list is `findings_scope.ciks` in `data/reference/quarter_acceptance_thresholds.json`; change the scope there, not in code.
- **What v0.5 does not change:** the public site shows the active manifest cohort described under V1 Scope (61 funds after the owner's 2026-10-20 deferral). Do not cut it to the five-fund remediation scope.
- **Do not widen on your own.** Work on the other ~65 funds only when it is needed to fix a v0.5 fund (a global rule, a shared extractor path) or the owner asks. Widening to v1 follows once v0.5 signs off cleanly.
- **Global fixes are still global.** An extractor or rule fix made for a v0.5 fund applies to every fund; check its effect on the full cohort with the semantic diff before accepting it.

## V1 Scope (Current Public Product)

The indices above describe the long-term vision. **The shipping v1 product is deliberately narrower: only the underlying position-level holdings data for the active BDCs in the wrapper-cohort manifest (61 as of 2026-10-20).** Keep this front of mind — do not reintroduce index surfaces or non-BDC vehicles into the public site without an explicit decision to expand scope.

- **What v1 ships:** for the active manifest cohort, the underlying position data (every loan, equity stake, and credit facility each fund discloses) plus per-fund and aggregate portfolio analytics (instrument/industry mix, concentration, spreads, credit stress, PIK).
- **Owner deferral, 2026-10-20:** nine smaller funds are deferred from public v1 and routine fund-clearing dispatch: NexPoint Capital (0001588272), SCP Private Credit Income (0001743415), PIMCO Capital Solutions (0001905824), BlackRock Direct Lending (0001834543), TCW Star (0001916608), Onex Direct Lending (0001860424), TriplePoint Private Venture Credit (0001792509), Audax Credit (0001633858), and Stellus Private Credit (0001901037). The manifest's `deferred_entries` preserves them separately from admission holdbacks; Saratoga remains an existing holdback. Retain their raw data, canonical holdings, corrections and unresolved findings. Deferral is not a disposition or a quality pass. Re-entry requires an owner decision. The acceptance five-fund scope is unchanged.
- **No indices in v1.** Position-level indices, index returns, "constituents", "indexed fair value", base-100 levels, and the `/indices` pages are NOT part of v1 and have been removed from the public frontend. Generic financial-charting math (e.g. a single fund's own total-return series rebased to 100) is not the index product and is fine to keep.
- **BDCs only.** Interval funds and tender-offer funds are still discovered/processed in the pipeline but are out of scope for the v1 public site.
- **Canonical cohort & FV.** The authoritative scope is the wrapper-cohort manifest `entries` (61 CIKs as of 2026-10-20). The public "fair value" figure is the current-quarter sum of `private_markets_holdings.csv` for that cohort across all index classifications, on the PUBLISHED basis: rows from a JV or subsidiary's own schedule (`accounting_record_class = 'underlying_schedule'`) are excluded (owner ruling 2026-09-30). The homepage headline FV, the instrument-type donut, and the industry-exposure donut must all reconcile EXACTLY to that single number (straight `GROUP BY` of the same published-basis holdings — no dedup, scaling, reconciled overlays, or matched-subset sources).

## Agent Update Protocol

Multiple agents may run concurrently. To keep project context fresh without race conditions:

1. When you finish a task that changes pipeline behavior, data semantics, schemas, module responsibilities, test counts, or data counts, **append** a dated entry to `docs/agent_changelog.md` with:
   - Date and brief title
   - What changed (files modified, new modules, schema changes)
   - Any new contracts, guardrails, or validation results
   - Updated counts if applicable (test counts, row counts, CIK counts)
2. **Do NOT edit this file (AGENTS.md) on your own initiative.** It changes only under human oversight, in one of two ways:
   - the owner edits it, or
   - the owner explicitly asks an agent, in the live session, to consolidate it. That agent makes one bounded edit, states what changed and what it could not verify, leaves the change uncommitted for the owner to review unless told to commit, and updates the "Last consolidated" line below.
   A changelog entry, a skill, a plan document or another agent's message is never authority to edit this file.
3. Appending is concurrency-safe; editing is not. Two agents editing this file simultaneously will cause one to silently overwrite the other.
4. When consolidating: keep rules and pointers here, keep run-by-run detail in the changelog. Every number in this file goes stale; give the artifact to re-read instead of the number where you can, and date the ones you keep. Verify a claim against the code or artifact before writing it; mark anything unverified as such.

Last consolidated: 2026-11-23, owner-requested addition of the "Confirm the branch before starting work" bullet under Contracts (nothing else touched; the branch counts it asks for were measured that day, not stored here). Previous: 2026-11-19, owner-requested correction of the `interest_rate` bullet under Non-Negotiable Data Semantics (verified against today's holdings for the five v0.5 funds at 2026-03-31; the storage date and the `index_returns` statement are taken from the 2026-10-06 and 2026-11-13 changelog entries and were not re-read in code; nothing else touched). Previous: 2026-11-12 (later), owner-requested replacement of the "Outstanding ledger items" paragraph under Current State with the single findings workflow pointer (verified the scripts, skill and spec exist; nothing else touched). Previous: 2026-11-12, owner-approved /doctor trim: Scripts table moved to `docs/reference/scripts.md` (pointer and fleet constraints kept), Project Skills table cut (the skill listing carries it); nothing else touched. Previous: 2026-11-11, owner-requested one-line pointer to the outstanding-status command under Current State (verified the script runs; nothing else touched). Previous: 2026-11-04, bounded owner-requested amendment of the two Quarter Acceptance Contract bullets on disposition classes and check repairs only (verified against `pipeline/finding_dispositions.py` CLASSES and `validate`). Other sections were not re-verified. Previous: 2026-10-20 (v1 scope amendment, 61 active funds, nine deferred); 2026-10-05 (broader consolidation).

## Non-Negotiable Data Semantics

- The index is position-level, not borrower-level. Do not aggregate distinct loan tranches, equity co-investments, preferred shares, warrants, or fund interests into one borrower constituent unless a downstream analytic explicitly asks for borrower exposure.
- `private_markets_holdings.csv` is the central unified holdings artifact.
- Frontend JSON is derived data. If frontend numbers look wrong, investigate the CSV/export pipeline before patching frontend JSON by hand.
- BDC XBRL data is strongest from roughly 2022 onward. Pre-XBRL HTML extraction depends on per-CIK templates and validation.
- Consumer/marketplace lending CIKs with opaque individual loan IDs are intentionally excluded from index-facing unified outputs because they inflate row counts while contributing little FV.
- Comparative-period BDC rows can be legitimate prior-period facts, not duplicates. Confirm `period`, `report_date`, accession, and dimension path before removing them.
- PIK has two separate meanings in this repo. `pik_current_status` is strict current-payment/accrual evidence from N-PORT paid-in-kind flags or BDC position-level PIK income/accrual/capitalization facts. `pik_terms_flag` / `pik_terms_rate` is a schedule-rate proxy for disclosed PIK terms, comparable to S&P-style BDC PIK exposure, but not proof of current PIK income.
- Do not label `pik_terms_started` as confirmed "bad PIK." It is a public-filing proxy that PIK terms appeared on an existing matched position. Confirmed bad PIK requires amendment/origination evidence showing cash-pay terms were changed because of borrower stress.
- `interest_rate` holds the all-in rate (decided 2026-07-12, stored that way since the 2026-10-06 financial contract). `interest_rate_cash` holds the cash leg, `pik_rate` the PIK leg, and `interest_rate_kind` says how the stored rate was read (`all_in`, `cash`, `unresolved`). A filer's rate tag is read through `source_encodings.filed_rate_reading` in its wrapper. A row with no supported reading stays `unresolved` with no rate; for some funds that is most rows (Blue Owl and Apollo at 2026-03-31), so a missing rate is not evidence that the position has none. `pipeline/index_returns.py` uses the all-in rate and must not add PIK on top. Do not change the stored meaning or the income formula separately.
- Conservation sums are subsidiary-aware (retain-and-flag, 2026-08-29): JV/subsidiary rows are kept in holdings and flagged via `is_subsidiary`, and the FV-conservation gate excludes them. Do not add a global JV/subsidiary drop.
- JV look-through rows are retained but NOT published (owner ruling 2026-09-30). The headline, the fund-level reconciliations, the PIK summaries and the acceptance gate all use the published basis, which excludes `underlying_schedule` rows. Do not swap a JV position for its underlying companies in the headline: the sum would stop reconciling to the fund's filed total, and gross JV assets are not comparable to the fund's stake. A look-through view, if built, is a separate labelled surface.
- Position matching uses contested name-key assignment with a maturity veto (promoted 2026-09-07) and is deterministic since 3810a8f (2026-09-30). The finalizer allocates identities through a durable registry (`pipeline/durable_identity.py`, `data/output/identity_registry.duckdb`); the older `pipeline/position_id_registry.py` stays opt-in (`use_registry` defaults False). Cross-rebuild stability of `position_id` was not re-measured at the 2026-10-05 consolidation: verify before using raw pids as cross-rebuild keys.
- Review-queue and findings-ledger ids are per fund, rule and period. Dates in id inputs must be `YYYY-MM-DD` strings: a pandas frame read from the typed parquet turns DATE into a timestamp and `CAST(... AS VARCHAR)` then yields `YYYY-MM-DD 00:00:00`, which has silently broken id hashing and period filters three times (0f28433, and the two 2026-10-04 changelog entries).

## Contracts

These are harm-category restrictions. Violating them causes data loss, silent corruption, or external service abuse.

- **No unwanted network calls.** Do not trigger SEC EDGAR downloads unless the user explicitly asks. All raw data is cached on disk. Use `scripts/rebuild_outputs.py` or call pipeline functions directly to rebuild outputs.
- **No production data corruption.** Pytest installs a monkeypatch guard (`tests/conftest.py`) that replaces `builtins.open` and `io.open` with wrappers blocking any write-mode open (`w`, `a`, `x`, `+`) to `data/output/` or `frontend/public/data/`. This covers all standard Python write paths (`open()`, `Path.write_text()`, `pandas.to_csv()`, `json.dump()`, etc.). Native-IO writers (DuckDB `COPY TO`, pyarrow) bypass `builtins.open`, so `conftest.py` also snapshots mtime/size of every file under the protected roots at session start and fails the session on any created/changed/deleted path. Historical note: verified 2026-05-18 at 1,956 tests; the suite is now ~5,000 test functions across 143 files. After running tests, run `python scripts/diff_outputs.py --semantic` as a backstop to confirm no artifact drift.
- **Baseline governance.** The active baseline (`data/snapshots/baseline/`, gitignored) was last refreshed 2026-09-05 after the Q1-2026 sign-off (rebuild-then-refresh at git `d18560d`). The prior baseline was archived by hand to `baseline_retired_2026-09-05`. Do not compare new work against retired or `pre_*` snapshots except for historical investigation. Refresh only after rebuilding from cached inputs, running `python scripts/diff_outputs.py --semantic`, documenting semantic deltas, and archiving the prior baseline first: `snapshot_outputs.py --clean` deletes the old baseline without archiving it.
- **No SEC rate-limit violations.** The existing `edgar_client.py` enforces 10 req/sec. Do not bypass it or add parallel request paths.
- **No encoding crashes.** All log messages must use ASCII only — Windows cp1252 cannot render Unicode box-drawing, em-dashes, or ellipsis characters.
- **No slow transforms on large datasets.** Avoid pandas `.apply()`, `.iterrows()`, or row-level Python loops on datasets with >10K rows — the pipeline's 800K+ row datasets will hang for minutes. Use DuckDB SQL or vectorized operations. Pandas is fine for small summaries and logging.
- **Commit messages.** Include a short subject line plus a brief body (2-4 bullet points or sentences) explaining what changed and why. Keep it concise -- no walls of text.
- **No ad-hoc inline Python scripts.** Do not launch `python -`, here-strings piped to Python, or long `python -c` snippets for repo-scale diagnostics. These have repeatedly left hidden high-memory processes running. Prefer existing scripts, targeted `pytest`, DuckDB CLI/SQL, `rg`, or short PowerShell inspection commands. If a temporary Python diagnostic is unavoidable, put it in a named temp file with explicit row limits, progress output, and a short timeout, and check/kill the process before continuing.
- **No duplicate long-running test jobs.** Before starting a full pytest suite or rebuild, check for existing pytest/rebuild processes from other agents. Do not run overlapping full suites or rebuilds unless the user explicitly asks.
- **Rebuilds are long and memory-bound.** `rebuild_outputs.py --unified` takes about 75-90 minutes on the full universe (not a minute), and its last stage needs well over 11 GB for the Python process on a 23.8 GB machine. Two runs on 2026-10-04 were killed for low memory with about 13 GB free at the start. Check free memory first, ask the owner before closing their applications, and log to `scratch/<date>_<topic>/`.
- **No code edits or pytest in a checkout while it rebuilds.** The build imports some modules late and stamps the release with hashes of its own source files; pytest's protected-output snapshot fails when the build publishes. Make changes in a git worktree (`.claude/worktrees/<name>`, `core.longpaths=true`) and merge after the build exits.
- **Do not revert user changes.** This repository often has a dirty worktree with active experiments, generated data, and ad-hoc scripts.
- **Confirm the branch before starting work (owner ruling 2026-11-23).** Before any work that will change tracked files, tell the owner which branch the checkout is on and how many branches are live (not merged into `main`) versus merged (`git branch --no-merged main`, `git branch --merged main`, `git worktree list`), and ask whether the work goes on a new branch. Do not start until the owner answers. One answer covers the plan it was given for, including that plan's subagents; a new piece of work needs a new answer. Read-only questions need no confirmation. One unit of work per branch: do not bundle unrelated work, and do not commit generated data with code unless the task is the data.

## Anti-Sycophancy Requirement

The user has finance and data-science context, but not necessarily software engineering context. Future agents must give professional engineering judgment, not validation of every premise.

Required behavior:

- Challenge requests that would make data quality less measurable, make validation weaker, or increase silent corruption risk.
- State when a proposed shortcut is unsafe, even if it seems to satisfy the immediate request.
- Separate "what the user asked for" from "what the system needs next" when they differ.
- Prefer evidence from source filings, deterministic reconciliation, tests, and measured validation outputs over intuition or narrative fit.
- Do not overstate confidence. If a metric is only a proxy for correctness, call it a proxy.
- Treat failed validation or unresolved ambiguity as a valid outcome. Do not force data to pass by widening filters, adding overrides, or suppressing checks without a mechanism and evidence.

In this project, politeness means being direct about risk.

## Priority Judgment

There are two competing next-step tracks:

1. Refactor the research-oriented codebase toward production code.
2. Improve frontend data accuracy and/or publish metrics that measure remaining inaccuracy.

The better next step is usually track 2 first.

Reason: refactoring before the data-quality contract is explicit can preserve wrong behavior behind cleaner abstractions. This codebase's main risk is long-tail filing idiosyncrasy: subtotal leakage, affiliation-axis duplication, identifier parsing variation, fund taxonomy errors, and rate-scale ambiguity. A cleaner module boundary does not solve those unless the target behavior is pinned down by source reconciliation and validation gates.

Refactoring is still necessary, but it should be driven by the data-quality architecture:

- Build or strengthen reconciliation first.
- Move per-CIK quirks out of global code where possible.
- Add tests around the measured behavior.
- Then refactor the implementation while preserving those gates.

## Implementation Guidance

Use existing patterns:

- DuckDB SQL for large CSV transformations.
- Small pandas DataFrames only for summaries, tests, and narrow in-memory operations.
- `pipeline.config` for paths and shared constants.
- `scripts/rebuild_outputs.py` for cached-data rebuilds.
- `pipeline.export_frontend.export_all()` for frontend JSON.
- Existing test helpers and fixture style in `tests/`.

When changing data logic:

- Add focused tests for the exact failure mode.
- Include at least one false-positive test when adding filters or keyword rules.
- Check whether the change belongs in global rules or per-CIK configuration.
- Rebuild affected outputs from cached data.
- Export frontend JSON if public UI data changes.

When changing frontend:

- Keep it consistent with the existing Next.js/Tailwind/Recharts app.
- Frontend should explain data status through metrics and provenance, not marketing copy.
- Do not hide uncertainty. Public trust is improved by showing validation status and known limitations.

## Verification Expectations

Choose verification proportional to the change:

- Pure docs change: no tests required.
- Small parser/classification change: targeted `pytest` file.
- Unified holdings change: targeted tests plus `python -m pipeline.main --unified --validate` or `python scripts/rebuild_outputs.py --unified` when practical.
- Export change: run `python -m pipeline.main --export-frontend` and inspect changed JSON shape.
- Frontend TypeScript/UI change: run `npm run build` in `frontend/`.
- CI (`.github/workflows/ci.yml`) runs only the no-cache subset of the suite (`needs_cache` split). Cache-dependent tests run locally only, so a green CI is not a full-suite pass.

### Test Selection Workflow

Use proportional verification. Do not run the full suite as the default inner loop.

- For a narrow parser/classifier change, run the exact test node or affected test file first.
- For unified holdings changes, run `tests/test_unified_holdings.py` and relevant validation tests, then rebuild unified outputs and run semantic diff when data semantics may change.
- For frontend-only changes, run the frontend build rather than pytest.
- Run the full pytest suite before merge/handoff, after broad refactors, or when shared contracts change.
- Use `--durations=50 --durations-min=0.5` on full-suite runs.
- Before starting a long pytest run, check for existing pytest processes and avoid overlapping full suites from multiple agents.

Always report what was and was not run.

## Agentic Data Quality Design

Agents should be subroutines inside a deterministic pipeline, not autonomous owners of the truth.

Preferred architecture:

- Layer 1: global deterministic transformation rules in Python/DuckDB.
- Layer 2: per-CIK corrections with schema, mechanism, evidence, confidence, and audit trail.
- Layer 3: fund-level metadata and strategy overrides grounded in N-CEN, prospectus language, or other source evidence.
- Validation layer: independent checks that the agent cannot satisfy by editing its own output.

Strong validation gates:

- Source reconciliation against cached XBRL or source filing facts.
- GAV/total-assets reconciliation against independent fund-level data.
- Cross-quarter position stability.
- Cross-layer fund strategy versus holdings mix.
- Classification cross-reference checks.
- Yield/rate sanity checks against fund income.

Weak validation checks are useful as flags, not gates:

- Generic pct-of-net-assets range checks.
- Null/fill-rate checks without source reference.
- Internal-only anomaly scores.
- "Metric improved" comparisons without a mechanism.

Every agent-authored correction should answer:

- What changed?
- Why is this the right mechanism?
- Which source evidence supports it?
- What metric changed before and after?
- What is the confidence?
- What residual risk remains?

Escalation is better than pretending. If no mechanism is found after bounded attempts, document the hypotheses tested and stop.

## Current Product Risk Register

Known high-value risks to keep in mind:

- Subtotal/category rows leaking into position-level holdings.
- Duplicate facts from multiple XBRL dimension paths.
- `pct_of_net_assets` inflation from duplicate dimension paths or wrong denominator.
- Fund-level strategy/taxonomy errors that holdings-level rules cannot catch.
- N-PORT source fields that are mislabeled by filers.
- Rate scale ambiguity.
- PIK terminology ambiguity: disclosed PIK terms, current PIK payment/accrual evidence, and "bad PIK" transitions are different metrics with different evidence strength.
- Entity resolution undercoverage, especially N-PORT.
- Public frontend charts implying precision that validation does not support.

Do not treat a visually plausible dashboard as evidence that the data is correct.

## Current State

Phases 1-6 (through the 2026-05 compatibility refactor) are complete; see [`docs/reference/phase_history.md`](./docs/reference/phase_history.md). Everything after that is recorded in `docs/agent_changelog.md`, which is authoritative for anything dated after 2026-05-28.

### Quarter Acceptance Contract (the live quality gate)

- Thresholds are data: `data/reference/quarter_acceptance_thresholds.json`, evaluated by `pipeline/quarter_acceptance.py`. Ten checks under v4: fund_coverage, reconcile_rate, flagged_fv_share, source_blocking_fv_share, verified_fv_share, promoted_rule_drift, promoted_rule_health, over_inclusion_fv_share, unfinished_investigations, outstanding_findings.
- **Sign-off rule (owner ruling 2026-10-05, v4 provisional): passing the FV-share bars is not enough.** `outstanding_findings` requires zero findings for the v0.5 funds at the sign-off quarter in any unresolved state: open in either lane, confirmed real with no fix, fix staged or pulled, waiting on a human, or waiting on evidence. Every finding ends fixed (data or extractor), cleared by a repaired check, or closed with a recorded disposition. The disposition store (`pipeline/finding_dispositions.py`) accepts only `as_filed`, `not_applicable` and `informational`. A finding where the check misfires (`rule_problem`, or a `false_alarm` caused by the check) is not a disposition: it clears only when the check is repaired (owner ruling 2026-11-04). Proposals must use the store's classes and carry a `rerun`. The source is the findings lifecycle ledger (`scripts/findings_ledger.py`; the quarter pass writes `findings_ledger_pre.csv` / `_post.csv`). A missing ledger or an unknown state fails the check.
- Never clear `outstanding_findings` by editing the scope or the ledger, or by widening a rule's tolerance. A check repair is allowed only with the owner's ruling, focused tests plus a test that a real error still fails, and a measurement on every accepted sandbox: list what it clears and adds, and it clears no finding that carries a real-error verdict (pattern: d7df345, 2026-11-04 changelog). A disposition needs cited evidence; an agent may propose it, a deterministic check or the owner accepts it. A rule that keeps misfiring for the same fund quarter after quarter gets repaired or retired for that fund.
- "All findings cleared" is not "data correct". No rule detects a change in what a field means, a wrong rate on the right row, or offsetting errors that leave totals intact. Say so wherever a clean result is reported.
- Why the rule exists: both signed-off quarters passed with more than half of their cohort findings outstanding (Q4-2025 434 of 796, Q1-2026 525 of 888 in the final pass ledgers), most of them confirmed errors never sent for a fix. For the v0.5 funds about 62 pct of confirmed-unfixed findings were systematic extraction gaps (no USD conversion of foreign principal, rates not captured, pct of net assets not extracted, currency fields from the wrong column, footnote non-accrual not carried), not row-level corrections. Fix those in the extractor or the filer's wrapper with a test; do not route them to B2. See `docs/investigations/agent_campaigns.md` (2026-10-05 entries).
- v2 signed off by the owner 2026-08-20 (reconcile >= 90, flagged <= 10, blocking <= 1, verified_fv >= 70).
- Q4-2025 (2025-12-31) PASS 7/7 under v2, git tag `signoff-2025-12-31`. Q1-2026 (2026-03-31) PASS 7/7 twice-stable, signed off 2026-09-05, git tag `signoff-2026-03-31`.
- v3 (2026-09-07, provisional) moves the numerator to the PUBLISHED basis and adds over_inclusion and unfinished_investigations. Q1-2026 re-run under v3 is EXPECTED to fail the FV-share checks; that is the gate seeing the over-inclusion, not a regression. The FV-share bars are still to be calibrated on Q2-2026 actuals.
- **Both signed-off quarters currently REGRESS on re-attestation** (since the 2026-09-30 base build, and they will also fail `outstanding_findings`). Treat the sign-off tags as history, not as a statement about today's build. Run `python scripts/reattest_quarters.py check` for the current reading before quoting either quarter as passing.
- Remediation cycle: `scripts/run_quarter_pass.py` (staged: rebuild, oracle, validate, provenance, shadow, queue, ledger, preflight, select) plus the `quarter-pass-operator` skill for Codex fleet dispatch and verify/promote. `scripts/reattest_quarters.py` re-attests signed-off quarters after any pipeline change; a regression there is a stop-and-report event.

**Outstanding findings (owner 2026-11-12, single findings workflow).** "Process outstanding ledger items" means the `findings-workflow` skill. Status comes from `python scripts/status.py`, written to `docs/investigations/findings_status.md`; quote counts only from it and give the batch id with every count. Production is the only build of record: fund sandboxes are scratch for testing a fix and have no status. Fixes enter production only through a batch (`scripts/run_batch.py`, one at a time, on the owner's go). Decisions are recorded only through `scripts/decide.py` into `data/decisions/` (append-only). Spec: `docs/superpowers/specs/2026-11-12-single-findings-workflow-design.md`.

### Current Blocker Accounting

When asked how many "blockers" remain, read the header of the latest source-reconciliation residual artifacts. Do not quote numbers from this file without re-checking.

Relevant artifacts:
- `data/output/source_reconciliation_source_only_classification.md` (totals in the header)
- `data/output/source_reconciliation_source_only_detail.csv`
- `data/output/source_reconciliation_residual_classification.md` / `.csv`
- `data/output/quarter_pass/<pass_id>/` for the per-pass battery, gate verdicts, and selected packets

At the 2026-09-08 rebuild the source-only pool was 9,335 blocking rows (of 15,338 source-only rows reviewed). The old 25-bundle `data/output/bdc_cik_review/` batch is historical only; do not regenerate a queue from it. Blocker selection now runs inside a quarter pass and ranks by output-side FV with a fund-leverage tiebreaker. Always state which artifact and timestamp/count basis you used.

### In flight (2026-10-05; this block goes stale fastest, check the changelog)

Main checkout is on `ensemble-fp-experiment`. Other work lives in worktrees under `.claude/worktrees/`.

- **Published data is the 2026-10-01 build.** Fixes committed since then (GICS labels no longer depend on the previous run, load-rejected promoted inputs fail the gate, review-id fixes) are not in the published holdings until a unified rebuild completes, followed by `--returns`, the frontend export, the semantic diff and re-attestation. Check `scratch/` for the latest rebuild log before starting another.
- **Acceptance v4** (`outstanding_findings`): commit 1907eaf, merged into `ensemble-fp-experiment` 2026-10-05. Open defect: outside a quarter pass the check reads `data/output/agent_b2/findings_ledger.csv`, which was last written 2026-08-16, and nothing rejects a stale ledger. Regenerate the ledger (`scripts/findings_ledger.py`) before trusting a standalone acceptance or re-attestation reading.
- **The unified rebuild does not complete on this machine at present.** Three attempts since 2026-10-04 were stopped for low memory (two at the hand-off to the finalizer, one inside it); the last completed build predates commit b665895. Cause not established. Do not start another without the owner; see the 2026-10-05 changelog entry.
- **Filer profiles** (branch `filer-profile-pilot`, pushed, not rebased): per-filer documents built for 8 pilot filers at 2025-12-31; nothing in production reads them; the sub-project 3 exit test is NOT met. Spec `docs/superpowers/specs/2026-09-29-filer-profile-programme-design.md` on that branch. Direction under review by the owner: the profile's first job becomes carrying finding dispositions forward (stable identity, validity condition, evidence) for the v0.5 funds, ahead of completing the full per-field document. Only two of the v0.5 funds (BCRED, Ares) are among the 8 pilot filers.
- **Known open defects on v0.5 funds:** HPS 2026-03-31 holdings sum about 6 pct above its filed total (a B2 fix was rejected by its gate); HPS net asset value per share extracted as 1000; BCRED drops 11 real positions; an Ares issuer rollup is double-counted. Re-check each against the current build before acting.
- Published-basis gate (v3) shipped with the underlying-schedule exclusion; remaining owner items in `docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md` and the 2026-09-30 changelog entries.
- Refactor "programme" builds: V13 retired by owner ruling, no V14. `data/programme/candidates/` keeps the two newest candidates only; history in `docs/production_stack/candidate_history_2026-10-03.md`.
- Jev screening pilot (worktree `jev-screening-pilot`): paused at the owner's request 2026-10-04; see its changelog entries before resuming.
- Match quality and chain completeness (`docs/superpowers/plans/2026-09-08-chain-completeness.md`) and the production stack (`docs/production_stack/`; Parquet companions live, CSV canonical until the reader flip) are unchanged since 2026-09-08 as far as this consolidation checked.

## Pipeline Architecture

```
python -m pipeline.main                  # Universe discovery (~5 min)
python -m pipeline.main --holdings       # + BDC XBRL extraction (~1-3 hrs first run)
python -m pipeline.main --ciks 1418076   # Holdings for specific CIKs only
python -m pipeline.main --unified        # Build unified private markets holdings (~75-90 min, memory-bound; see Contracts)
python scripts/rebuild_outputs.py --pik-status  # Strict current PIK status artifacts
python scripts/rebuild_outputs.py --pik-proxy   # S&P-style schedule-rate PIK proxy artifacts
python scripts/run_quarter_pass.py --list                                   # list quarter-pass stages
python scripts/run_quarter_pass.py --pass-id <id> --quarter YYYY-MM-DD      # staged remediation pass (see --from/--until/--dry-run)
python -m pipeline.quarter_acceptance --quarter YYYY-MM-DD                  # gate verdict vs data/reference thresholds
python scripts/reattest_quarters.py check --quarter YYYY-MM-DD              # re-attest a signed-off quarter
```

Outputs: CSVs under `data/output/` are canonical. Eleven core artifacts also have typed Parquet companions (`*.parquet`, same stem) written by DuckDB; readers still consume the CSV until the reader flip lands.

For the module inventory and test coverage table, see [`docs/reference/modules_and_tests.md`](./docs/reference/modules_and_tests.md). That file, `data_layout.md`, and `phase_history.md` are dated 2026-05-28; for modules added since (quarter pass, shadow engines, provenance, position_id registry, match quality) use `docs/agent_changelog.md`.

## Data Layout

See [`docs/reference/data_layout.md`](./docs/reference/data_layout.md) for the full directory tree of `data/output/` and `data/raw/`.

## Schemas & Validation

See [`docs/reference/schemas.md`](./docs/reference/schemas.md) for BDC holdings schema, PIK status outputs, and unified holdings validation (V1-V7) details.

## Known Limitations & Technical Details

See [`docs/reference/known_limitations.md`](./docs/reference/known_limitations.md) for XBRL coverage gaps, HTML template extraction, resumability, XBRL data source discovery, and oversubscription data.

## Data Investigations

Ad-hoc data analyses (e.g., classification stability, outlier deep-dives, coverage checks) are filed under `docs/investigations/` (git-tracked; see `INDEX.md` there for topics). Append each new investigation to the matching topic file with a dated heading, the question asked, and the results found, then rebuild the index: `python scripts/split_investigations.py --reindex`. The old `data/output/data_investigation_results.md` is a frozen redirect stub (cutover 2026-08-20) -- do not append there.

## Session Scratch

Ad-hoc artifacts from interactive operator/agent sessions -- shell redirect logs (`command > foo.log`), one-off plots, session kickoff notes, throwaway dumps -- go under `scratch/` in a per-session subdirectory named `YYYY-MM-DD_<topic>/` (git-ignored except its README; see `scratch/README.md`). Do not leave them in the repo root. Machine-written fleet/pipeline logs are out of scope and stay in their existing homes: `data/output/pipeline.log`, `data/output/quarter_pass/<pass_id>/<stage>.log`, and the agent batch dirs -- those are run provenance, not scratch. Scratch is disposable: once findings are recorded in `docs/investigations/` or the changelog, the session dir can be deleted.

## Frontend

Next.js 14 dashboard in `frontend/`. Reads static JSON from `frontend/public/data/`.

```
cd frontend
npm run dev -- -p 3004    # Dev server at http://localhost:3004
npm run build             # Static export to frontend/out/
```

## Scripts

Main operator scripts and their usage: [`docs/reference/scripts.md`](./docs/reference/scripts.md). Codex worker fleets: dispatch from an ADMIN PowerShell, MaxParallel ceiling 2. Project skills are in `.claude/skills/`; read the SKILL.md before use, and do not improvise around `quarter-pass-operator`'s escalation boundaries.

## Files Worth Reading First

- `AGENTS.md` (this file): current state, contracts, schemas, and operational warnings.
- `docs/reference/codex_worker_dispatch.md`: how to dispatch sandboxed Codex worker fleets (the
  reusable pattern + the four sandbox traps). Read before standing up any new terminal agent set.
- `docs/agentic_data_quality.md`: the agentic validation architecture (2026-05 proposal; now largely implemented as the quarter-pass cycle).
- `pipeline/quarter_acceptance.py` and `data/reference/quarter_acceptance_thresholds.json`: the live quality gate and its thresholds.
- `scripts/run_quarter_pass.py`: the remediation cycle that feeds the gate.
- `scripts/findings_ledger.py`: the finding lifecycle states behind the sign-off rule.
- `docs/investigations/agent_campaigns.md` (2026-10-05 entries): rule carry-forward between sign-offs and what the v0.5 funds' unfixed findings are.
- `docs/production_stack/production_data_stack_plan.md`: Parquet/dbt/R2 production stack plan and phase status.
- `docs/reference/match_gold_dispatch.md`: how position-match gold-set fleets are dispatched and scored.
- `pipeline/unified_holdings.py`: central holdings construction and classification.
- `pipeline/bdc_position_pik.py`: cache-only BDC XBRL extractor for position-level PIK income/accrual/capitalization evidence.
- `pipeline/pik_status.py`: strict current PIK status, PIK schedule-rate proxy summary, and PIK terms-started transition outputs.
- `pipeline/validate_holdings.py`: validation suite and output files.
- `pipeline/export_frontend.py`: public JSON aggregation.
- `pipeline/main.py`: orchestration and command flags.
- `pipeline/config.py`: paths, SEC settings, CIK exclusions, frontend cutoff.
- `tests/test_unified_holdings.py`: regression coverage for holdings rules.
- `tests/test_validate_holdings.py`: validation behavior.
- `frontend/src/lib/data.ts` and `frontend/src/lib/types.ts`: frontend data contract.

## Production Refactor Direction

When refactoring does become the priority, the safest direction is:

- Separate extraction, normalization, correction, validation, and export boundaries.
- Move filer-specific quirks into data/config with schemas.
- Make validation outputs first-class artifacts consumed by frontend and agents.
- Keep global rules small, heavily tested, and evidence-backed.
- Preserve CLI behavior unless deliberately changing the operator workflow.

Avoid large aesthetic rewrites. The productive refactor is one that reduces silent-data-corruption risk or makes validation easier to reason about.

## Current Tracks

Track 2 (data quality first) was chosen and its original six-step sequence is done: the quarter acceptance contract, deterministic source reconciliation, fund-strategy validation, audited per-CIK corrections, agents scoped to residuals with escalation, and quality tiers in the shadow ledger. The objective behind them (owner, 2026-10-05): cut the per-fund, per-quarter work. A fix or a disposition made in quarter x should keep working in quarter x+1, with a check that says when it has stopped fitting. Measured baseline between the two sign-offs: no wrapper changed, but 35 new rules were needed across 27 of 70 funds and 30 of those 35 are tied to one filing's rows, so they cannot carry forward.

The open tracks as of 2026-10-05, in priority order, all scoped to the v0.5 funds first:

1. **Restore a trustworthy current build.** Complete the unified rebuild, `--returns`, frontend export, semantic diff and re-attestation; merge acceptance v4.
2. **Clear the v0.5 backlog.** Fix the systematic extraction gaps in the extractor or wrapper (start with the HPS overshoot, then foreign-currency principal, rate capture, pct of net assets). Route the row-level remainder through B2. Give every remaining finding a recorded disposition. Target: `outstanding_findings` = 0 for the sign-off quarter.
3. **Make dispositions and rules carry forward.** Filer profiles, re-aimed at storing dispositions and reusable (not row-pinned) rules for the v0.5 funds. Headline measure per quarter: share of findings auto-cleared by a still-valid disposition versus newly reviewed, and the count of new per-fund fixes.
4. **Detection beyond the existing rules.** Pipeline integrity checks on every build (determinism, unique ids, explained row-count change); then the pilot checks (rollup, composition, row-by-row census comparison); then an agent reading pass for changes of meaning, measured on recall, false alarms and repeat-run stability before it is relied on.
5. **First out-of-sample quarter.** Q2-2026 for the v0.5 funds. Downloading the filings needs the owner's explicit go.
6. **Then widen** to v1 (the active manifest cohort) and resume the parked tracks: FV-share bar calibration, the production stack reader flip and R2 backup, match quality and chain completeness.

Before starting new work, read the last few `docs/agent_changelog.md` entries: the state above moves faster than this file.
