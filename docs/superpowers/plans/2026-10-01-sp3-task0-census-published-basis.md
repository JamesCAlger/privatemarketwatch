# SP3 Task 0: Census Published-Basis Partition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the pilot a census-side published-basis partition (the ordered predicate validated on 2026-10-01) so the `independent_totals` kind and the income proofs evaluate the same row set production publishes, then re-measure the totals floor on all eight filers.

**Architecture:** One pure module `scripts/profile_pilot/census_published.py` implements the seven ordered rules from `scratch/2026-10-01_census_published_basis/findings.md` as a function over a census document, returning per-position `(published: bool, rule: str)` plus the extra cash-equivalent-axis facts. `contracts_totals.observe_totals` consumes it. The partition is recorded on each totals contract as `applies_to = {"census_published": <predicate version>}` so the profile document (sub-project 3 proper) can carry it as a partition-structure entry. The seed, back-test and replay need no interface change.

**Tech Stack:** Python 3, pytest via `scripts/profile_pilot/verify.py`, DuckDB only in tests that read the investigation CSVs.

**Spec:** `docs/superpowers/specs/2026-09-29-filer-profile-programme-design.md` sections 4 (partition predicate; row position is never a predicate), 4.1, 5 (independent totals), 7.1; the 2026-09-30 amendment to the published-basis gate spec (underlying-schedule rows leave the basis); the investigation record in `docs/investigations/conservation_shadow_engine.md` (2026-10-01 entry). Controller rulings in `.superpowers/sdd/2026-09-30-sp1-drift-replay/progress.md`.

## Global Constraints

- Code only in the worktree `.claude/worktrees/filer-profile-pilot` (branch `filer-profile-pilot`); data in the main checkout `data/`. Tests only through the launcher (`verify.py test`, fresh run ids `sp3-verify-*`). Real runs alone under the lease (R36), run ids prefixed `stageb2-` / `stageb-` as R18 requires (`stageb2-sp3census-*` is NOT needed: reuse census `stageb2-sp1census-20260930t2235z` and profile `stageb-profile-sp1-20260930t225432z`).
- No unrequested network; no writes under `data/output` or `frontend/public/data`; ASCII; no inline python for diagnostics; write-once run roots.
- The predicate is DATA about the filer, versioned: `CENSUS_PUBLISHED_VERSION = "census-published.v1"`; rule text and the per-filer reporting-entity list are constants in the module for this task and become profile entries in sub-project 3. Changing a rule is a new version.
- The pre-registered totals bands and floors do not change. The anchor stays `fund_financials.investments_at_fair_value` (the production anchor); the balance-sheet-vs-production question and the money-market-fund question are owner items and are NOT decided here (named money-market funds stay published, matching production).
- Every number reported is IN-SAMPLE.

---

### Task 1: `census_published.py`, the predicate as pure functions

**Files:**
- Create: `scripts/profile_pilot/census_published.py`
- Test: `tests/test_profile_pilot_census_published.py`

**Interfaces:**
- Consumes: a census document (`result` object): `positions[*]` with `context_id`, `period.instant`, `fields.<name>.value`, `identity.typed_identifier`; `document_metadata.document_period_end_dates` and the DocumentPeriodEndDate fact; `contexts` (for R7 cash-equivalent-axis facts).
- Produces:

```python
CENSUS_PUBLISHED_VERSION = "census-published.v1"
REPORTING_ENTITIES = {"0001803498": ("Emerald JV LP", "Verdelite JV LP")}   # R6 list per filer (v1 data)
RULES = ("R1_own_period_instant", "R2_fv_not_reported", "R3_label_or_heading", "R4_generic_cash_bucket",
         "R5_issuer_rollup_fv_only", "R6_reporting_entity_lookthrough")

def classify(doc: dict, *, cik: str) -> dict
    # -> {"version": CENSUS_PUBLISHED_VERSION, "period_end": "YYYY-MM-DD",
    #     "rows": {context_id: {"published": bool, "underlying": bool, "rule": str | None}},
    #     "extra_fv_facts": [ {"context_id", "fair_value", "source": "R7_cash_equivalent_axis"} ],
    #     "removed_by_rule": {rule: {"n": int, "fv": float}}}

def published_positions(doc: dict, *, cik: str) -> list[dict]      # positions with published=True
def published_fv_sum(doc: dict, *, cik: str) -> Decimal            # sum over published positions + extra_fv_facts
```

Rule semantics (verbatim from the investigation; each is one small function):
- R1: keep positions whose `period.instant` equals the document's own period end (the DocumentPeriodEndDate fact value; fall back to `max(document_period_end_dates)` and record which was used).
- R2: drop positions whose `fields.fair_value.value` is None or "".
- R3: drop when any `|`-separated segment of `identity.typed_identifier`, lower-cased and stripped, starts with `total` or `subtotal`, equals `net assets`, or starts with `controlled affiliated investments` / `non-controlled affiliated investments` / `non-controlled/non-affiliated investments` (the segment is a heading, not an issuer).
- R4: drop when a segment equals or starts with `cash and cash equivalents` or `other cash and cash equivalents`; a segment naming a money-market fund (contains `money market` or `fund` with a share count) is kept.
- R5: drop a position when fair_value is its only reported numeric field AND its typed identifier is a strict prefix (before the first `|`) of at least two other kept positions' identifiers AND its fair value equals the sum of those positions' fair values within 0.5 percent.
- R6: mark `underlying=True` (not published) when any segment after the first equals one of the filer's `REPORTING_ENTITIES`; a filer with no list marks nothing.
- R7: for contexts whose dimensions include a cash-equivalent axis member with an `InvestmentOwnedAtFairValue` fact at the own-period instant and no census position, emit an extra FV fact.

- [ ] **Step 1: Write the failing tests.** Fixtures: build small docs with the `mk_doc`/`debt` helpers from `tests/test_profile_pilot_contracts.py`, adding typed identifiers via the `ident=` argument, plus one recorded fixture per rule taken from `scratch/2026-10-01_census_published_basis/census_rule_assignments_v2.csv` (copy the 12 rows that carry a rule into `tests/fixtures/census_published_v2_rows.csv`; the test asserts `classify` assigns the same rule to each). Tests: one per rule (removed and a near-miss kept), R6 on a BCRED-shaped doc (Emerald suffix marks underlying, a first-segment match does not), R7 emits the Fidelity-style fact, `published_fv_sum` equals sum of kept plus extra, version constant present, and a doc without typed identifiers passes through R3-R6 untouched.
- [ ] **Step 2: Run to fail** through the launcher (`sp3-verify-t1a`, `--no-pre-backstop`).
- [ ] **Step 3: Implement** the module (about 150 lines, ASCII, Decimal arithmetic, no I/O).
- [ ] **Step 4: Run to pass** (`sp3-verify-t1b`).
- [ ] **Step 5: Commit** (`Add the census published-basis partition predicate (census-published.v1)`).

### Task 2: totals kind evaluates on the published partition

**Files:**
- Modify: `scripts/profile_pilot/contracts_totals.py` (`observe_totals`, `learn_totals`, `evaluate_totals`), `scripts/profile_pilot/contracts.py` (pass `cik` where needed; the totals contract's `applies_to` becomes `{"whole_filing": True, "census_published": CENSUS_PUBLISHED_VERSION}`), `scripts/profile_pilot/m2_backtest.py` (`_trim` keeps `applies_to`), `scripts/profile_pilot/replay_report.py` (per-filer table adds `removed_by_rule` totals from the seed run summary if present)
- Test: `tests/test_profile_pilot_totals.py`, `tests/test_profile_pilot_census_published.py`

**Interfaces:**
- `observe_totals(doc, *, financials, cik)` now sums `census_published.published_fv_sum(doc, cik=cik)` and counts `n_positions` over published positions; `pct_sum` over published positions with a filled pct; evidence carries `removed_by_rule`.
- `learn_totals(cik, tier, band, q1_doc, *, financials_q1)` and `evaluate_totals(contract, q2, q2_doc, *, financials_q2, band)` unchanged in signature; they pass `cik` through.
- `_check_frozen` equality is unaffected (band unchanged). The `applies_to` change affects the contract id? No: `contract_id` keeps `whole_filing` as partition_id; `applies_to` gains the key only.

- [ ] **Step 1: Failing tests:** a BCRED-shaped doc with 3 parent positions (FV 100, 200, 300), 2 Emerald rows (50, 60), one "Total" row (600) and one cash-bucket row (10): `observe_totals` returns `fv_sum == 600`, `n_positions == 3`, `removed_by_rule` shows R3 1 row / 600, R4 1 / 10, R6 2 / 110; with anchor 600 the contract holds; the previous `book()` tests still pass (their rows have no identifiers, so nothing is removed).
- [ ] **Step 2: Run to fail** (`sp3-verify-t2a`), **Step 3: implement**, **Step 4: run** the totals, contracts, seed, backtest and replay test files (`sp3-verify-t2b`), **Step 5: commit**.

### Task 3: re-measure and record

- [ ] **Step 1:** commit first; then, alone under the lease: `contracts_run --tolerances-version 4` (new `stageb-contracts-sp3-<stamp>` on census `stageb2-sp1census-20260930t2235z`, profile `stageb-profile-sp1-20260930t225432z`), `m2_seed` full (no `--semantic`) and `m2_seed --semantic`, `m2_backtest --semantic --tolerances-version 4 --seed-run-id <semantic seed>`, `replay_report --seed-run-id <full seed>`.
- [ ] **Step 2:** expected: totals contracts hold in the null control on all 8 filers (residuals -0.08% to +0.26%), `fair_value_scale_flip` applicable 8/8; report the median smallest detected fraction and the per-filer table; replay FA upper for totals drops from 0.80 (record the new value whatever it is); the standing-breach queue rows disappear or shrink.
- [ ] **Step 3:** changelog entry (`SP3 Task 0: census published basis`), spec section 8 row 3 note ("partition predicate v1 in code; becomes entries in Task 3 proper"), ledger, memory. Record the three production defects as open items for the production branch (BCRED 11 dropped positions, Ares rollup double count, Stepstone context ids).

## Self-review

Spec coverage: section 4 (structural predicate, versioned) Task 1; section 5 (totals on the published basis) Task 2; section 7.1 (knowledge families as data) partially, the R6 list is code data in v1 and moves to entries in SP3 Task 3. Placeholders: none; rule text is verbatim from the investigation. Types: `classify` returns the dict Task 2 reads (`rows`, `extra_fv_facts`, `removed_by_rule`).
