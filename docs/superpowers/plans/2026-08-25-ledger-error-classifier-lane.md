# ledger-error-classifier Lane (build only, NO dispatch) -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the classifier-family lane that adjudicates provenance-reverifier blocker flags (engine `provenance_reverify`: filing_mismatch, anchor_missing, ...) into routed verdicts -- packets, verdict-leaf schema with gate-side re-derivation, prompts, and dispatch manifests -- WITHOUT running any worker (no admin shell; dispatch is a future operator action).

**Architecture:** Four pieces, all riding existing machinery: (1) a provenance worklist projection in `pipeline/review_queue.py` (template: `bdc_worklist_projection`, which filters `engine=='source_recon'` only -- the reason these items are currently undispatchable); (2) a NEW verdict module `pipeline/ledger_error_verdict.py` mirroring `verdict_leaf.py`'s committed conventions with the lane's adjudication vocabulary and a fail-closed gate that re-derives every citation from the provenance ledger; (3) a dispatch-preparation CLI `scripts/ledger_error_classifier/build_dispatch.py` mirroring `scripts/agent_b2/dispatch_preflight.py`'s batch layout (worklist.csv, prompts/, manifest.json) minus everything write-granting -- classifier grants are read-only; (4) a no-dispatch verification: build the real batch from the live queue, and prove the verdict gate works by validating hand-authored sample leaves in tests. Evidence bundles already exist (`review_bundles.py` attaches provenance ledger slices) and are reused untouched.

**Tech Stack:** Python 3.x, DuckDB (ledger re-derivation reads), pytest. No new dependencies.

**Spec:** `docs/provenance_columns_scoping.md` sections 8.2-8.6 (adjudicator gets the residue; verdicts re-derivable gate-side; lanes reuse the worker harness; classifier family = read-only verdict leaves) and `docs/agent_family_architecture.md`'s convergence checklist, verbatim: (1) output is a verdict leaf, never free text; (2) escalation is a first-class sibling artifact (`*.escalation.json`); (3) the gate is deterministic and lives outside the agent's write reach; (4) grant profile documented per-lane at dispatch; (5) evidence citations sufficient for gate-side re-derivation; (6) prompt scaffolding taken from the nearest family sibling (B1 `bdc_cik_review.build_prompt`), divergences documented; (7) dispatch unit + dedup-against-existing-queues defined before the first canary.

## Global Constraints

(scout-verified facts + repo contracts; binding on every task)
- **NO DISPATCH.** Nothing in this plan runs a worker, invokes `dispatch_agent_b2_workers.ps1`, or touches Codex homes. The manifest carries an explicit `"dispatch_requires": "admin_shell"` marker. Building batches, prompts, manifests, and validating sample leaves is the entire scope.
- Queue facts: provenance items carry `review_id` minted by `review_queue._review_id` (`RVQ_BLK_<hash12>` pattern -- reuse, never re-mint); available fields per item = `REVIEW_QUEUE_COLUMNS` (:57) incl. `rule_name` (the reason_code), `n_units`, `fv_at_risk_m`, `confidence`. `bdc_worklist_projection` (:350) is the projection template. Blocker lane only (tight/fail codes); warn-lane items are NOT packets.
- Bundles: `review_bundles.build_review_bundles` already attaches provenance evidence (`_PROVENANCE_KEEP_COLS` 12 columns incl. cheap_status/full_status) into `data/output/review_queue/review_bundles/{review_id}.json` with `review_bundle_manifest.csv`. REUSE -- do not modify `review_bundles.py` (it also carries a foreign uncommitted hunk).
- Verdict-leaf conventions (from committed `verdict_leaf.py` -- REQUIRED_KEYS `(review_id, verdict, confidence)`, confidence float in [0,1], escalation via `escalate: true` + `{review_id}.escalation.json` sibling, decided-verdict evidence requirements): mirror the SHAPE in the new module; do NOT edit `verdict_leaf.py` (dirty file, different lane vocabulary). Divergences documented in the module docstring.
- Verdict store: `data/output/review_queue/verdicts/{review_id}.json` (shared across classifier lanes -- same store B2 preflight reads).
- Batch layout (from `dispatch_preflight.py`): `data/output/ledger_error_classifier/batch/<batch_id>/` containing `worklist.csv`, `prompts/{review_id}.md`, `manifest_<wave>.json` + `manifest.json`. Manifest fields mirror B2's minus `corrections_dir`: batch_id, created_at, worker_python, worker_read_dirs (READ-ONLY grant list: data/output/review_queue/review_bundles, data/output/provenance_ledger.csv, data/output/private_markets_holdings.parquet, data/raw/filings/bdc_xbrl), n_dispatch, rows[] with (review_id, cik, report_date, reason_code, prompt_path, bundle_path, verdict_path, lock_key), plus `"grant_profile": "read_only_classifier"` and `"dispatch_requires": "admin_shell"`.
- Cohort guard at the dispatch chokepoint: `pipeline.cohort_guard.check_worklist` on the batch worklist before writing the manifest; refuse out-of-cohort.
- AGENTS.md: ASCII-only; no inline `python -`; DuckDB for ledger reads (676MB -- filtered, parameterized, capped, per the review_bundles precedent); pytest write-guard (tests use tmp_path); stage only named files; B3-dirty files untouched (`verdict_leaf.py`, `review_bundles.py`, `agent_b2_appliers.py`, `correction_leaf.py`, `scripts/agent_b2/*` + their tests); commit style short subject + bullets.
- 8.2 boundary honored: the classifier adjudicates only what deterministic triage cannot -- packets are built from queue reason codes as-is; the PROMPT instructs adjudication INTO `{extraction_wrong, parser_drift, filer_error, amended, false_flag}`, it never re-litigates the deterministic reason code itself.

## File Structure

| File | Change | Task |
|---|---|---|
| `pipeline/review_queue.py` (clean) | `provenance_worklist_projection()` + `--emit-provenance-worklist` CLI | 1 |
| `pipeline/ledger_error_verdict.py` (new) | verdict schema, validator, gate-side re-derivation | 2 |
| `scripts/ledger_error_classifier/build_dispatch.py` (new) | batch builder: worklist, prompts, manifest (no dispatch) | 3 |
| `tests/test_review_queue.py` (locate: `rg -l "bdc_worklist_projection" tests/`; create section) | projection tests | 1 |
| `tests/test_ledger_error_verdict.py` (new) | schema + gate tests | 2 |
| `tests/test_ledger_error_classifier_dispatch.py` (new) | batch-builder tests | 3 |
| `docs/agent_family_architecture.md` (untracked-but-existing doc; verify clean) + `docs/reference/schemas.md`, `docs/agent_changelog.md` | lane record | 4 |

---

### Task 1: Provenance worklist projection

**Files:**
- Modify: `pipeline/review_queue.py` (next to `bdc_worklist_projection` ~:350; CLI arg where `--emit-bdc-worklist` is defined)
- Test: the file housing `bdc_worklist_projection` tests (locate; else create `tests/test_review_queue_provenance.py`)

**Interfaces:**
- Consumes: `REVIEW_QUEUE_DIR / "review_queue.csv"` items.
- Produces: `provenance_worklist_projection(*, queue_path=None, items=None) -> list[dict]` filtering `engine == 'provenance_reverify' AND lane == 'blocker'`, projecting `PROVENANCE_WORKLIST_COLUMNS = ["review_id", "cik", "report_date", "reason_code", "n_units", "fv_at_risk_m", "confidence", "priority_rank"]` (reason_code = item `rule_name`; all values normalized as the sibling does); writer to `REVIEW_QUEUE_DIR / "provenance_worklist.csv"`; CLI flag `--emit-provenance-worklist` alongside the existing flag.

- [ ] **Step 1: Write the failing tests**

```python
class TestProvenanceWorklistProjection:
    def _items(self):
        base = {"lane": "blocker", "engine": "provenance_reverify",
                "rule_name": "filing_mismatch", "cik": "0001287750",
                "report_date": "2025-12-31", "review_id": "RVQ_BLK_abc123def456",
                "n_units": "12", "fv_at_risk_m": "3.25", "confidence": "",
                "priority_rank": "4"}
        return [
            dict(base),
            {**base, "engine": "source_recon", "review_id": "RVQ_BLK_other1"},
            {**base, "lane": "review", "rule_name": "no_provenance",
             "review_id": "RVQ_REV_warnrow1"},
        ]

    def test_filters_engine_and_lane(self):
        rows = provenance_worklist_projection(items=self._items())
        assert [r["review_id"] for r in rows] == ["RVQ_BLK_abc123def456"]
        assert rows[0]["reason_code"] == "filing_mismatch"

    def test_columns_exact(self):
        rows = provenance_worklist_projection(items=self._items())
        assert list(rows[0].keys()) == PROVENANCE_WORKLIST_COLUMNS
```

- [ ] **Step 2: Run to verify failure** -- ImportError.
- [ ] **Step 3: Implement** by structural analogy with `bdc_worklist_projection` (same normalization helpers, same writer pattern, same CLI wiring), preserving queue review_ids verbatim.
- [ ] **Step 4: Run tests** -- new tests + the sibling projection's existing tests green.
- [ ] **Step 5: Commit** `git add pipeline/review_queue.py <test file>`; message: "ledger-error-classifier: provenance worklist projection" + 2 bullets.

---

### Task 2: Verdict leaf + gate-side re-derivation (`pipeline/ledger_error_verdict.py`)

**Files:**
- Create: `pipeline/ledger_error_verdict.py`
- Test: `tests/test_ledger_error_verdict.py`

**Interfaces (the lane's contract -- Tasks 3-4 and the future dispatch depend on these exact names):**
- `ADJUDICATIONS = ("extraction_wrong", "parser_drift", "filer_error", "amended", "false_flag", "ambiguous")`
- `REQUIRED_KEYS = ("review_id", "verdict", "confidence")`
- `validate_ledger_verdict(leaf: dict) -> dict` -- pure schema validation returning `{"ok": bool, "errors": [...], "warnings": [...]}` with rules:
  - confidence float in [0,1]; unknown verdict -> error.
  - `extraction_wrong` and `parser_drift` REQUIRE non-empty `mechanism` AND >=1 `culprit_citations` entry of shape `{"row_id": str, "field": str, "declared_raw": num|None, "instance_raw": num|None, "published": num|None}`.
  - `parser_drift` additionally REQUIRES `drift_fingerprint = {"field": str, "transform_code": str, "affected_row_ids": [>=1 str]}` (the parser-patch lane's future packet key, scoping 8.3).
  - `filer_error` REQUIRES `filer_error_basis` (free text, non-empty) and >=1 citation -- it is an escalation-shaped outcome: warn if `escalate` is not true.
  - `amended` REQUIRES `superseding_accession` (non-empty string).
  - `ambiguous` REQUIRES `ambiguity_basis in ("evidence_insufficient", "source_unavailable")`; `source_unavailable` should set `escalate: true` (warning, mirroring the sibling).
  - Escalation sibling convention documented: `{review_id}.escalation.json`.
- `rederive_citations(leaf: dict, *, ledger_path: Path | None = None, ledger_df=None) -> dict` -- THE GATE (fail-closed): for every `culprit_citations` entry, re-load the provenance ledger row by `(row_id, field)` (DuckDB parameterized filtered read; `ledger_df` injectable for tests) and confirm: the row exists; its `reason_code` is a tight code; every cited numeric (`declared_raw`/`instance_raw`/`published`) matches the ledger value within rel-tol 1e-9 (None matches NULL). Any miss -> `{"ok": False, ...}` with the mismatch named. A verdict whose citations do not reproduce is REFUSED regardless of schema validity.
- `validate_dir(verdicts_dir: Path, worklist_path: Path, *, ledger_path=None) -> dict` -- batch intake: every worklist review_id has a verdict or an `.escalation.json` sibling; no unknown/duplicate review_ids; each verdict passes schema + re-derivation; returns per-file results + summary counts.
- Module docstring records divergences from `verdict_leaf.py` (different vocabulary; ledger-based re-derivation instead of citation-quote checks; same escalation and confidence conventions).

- [ ] **Step 1: Write the failing tests** (the load-bearing ones; add the symmetric negatives):

```python
def _leaf(**kw):
    base = {"review_id": "RVQ_BLK_abc123def456", "verdict": "extraction_wrong",
            "confidence": 0.8, "mechanism": "wrong_concept_selected",
            "culprit_citations": [{"row_id": "ROW-aaaa", "field": "fair_value",
                                   "declared_raw": 1000.0, "instance_raw": 1000.0,
                                   "published": 990.0}]}
    return {**base, **kw}

def _ledger_df():
    return pd.DataFrame([{
        "row_id": "ROW-aaaa", "field": "fair_value", "reason_code": "filing_mismatch",
        "declared_raw": 1000.0, "instance_raw": 1000.0, "published": 990.0,
        "cheap_status": "pass", "full_status": "published_mismatch",
        "cik": "0001287750", "report_date": "2025-12-31",
        "expected": 1000.0, "src_context_id": "ctx1"}])

class TestSchema:
    def test_extraction_wrong_requires_mechanism_and_citation(self):
        assert validate_ledger_verdict(_leaf())["ok"]
        assert not validate_ledger_verdict(_leaf(mechanism=""))["ok"]
        assert not validate_ledger_verdict(_leaf(culprit_citations=[]))["ok"]

    def test_parser_drift_requires_fingerprint(self):
        leaf = _leaf(verdict="parser_drift",
                     drift_fingerprint={"field": "interest_rate",
                                        "transform_code": "rate_x100",
                                        "affected_row_ids": ["ROW-aaaa"]})
        assert validate_ledger_verdict(leaf)["ok"]
        assert not validate_ledger_verdict(_leaf(verdict="parser_drift"))["ok"]

    def test_amended_requires_superseding_accession(self):
        ok = _leaf(verdict="amended", superseding_accession="0001-26-000009")
        assert validate_ledger_verdict(ok)["ok"]
        assert not validate_ledger_verdict(_leaf(verdict="amended"))["ok"]

class TestRederivation:
    def test_matching_citation_passes(self):
        assert rederive_citations(_leaf(), ledger_df=_ledger_df())["ok"]

    def test_fabricated_value_refused(self):
        bad = _leaf(); bad["culprit_citations"][0]["instance_raw"] = 555.0
        out = rederive_citations(bad, ledger_df=_ledger_df())
        assert not out["ok"] and "instance_raw" in str(out["errors"])

    def test_unknown_row_refused(self):
        bad = _leaf(); bad["culprit_citations"][0]["row_id"] = "ROW-zzzz"
        assert not rederive_citations(bad, ledger_df=_ledger_df())["ok"]
```

- [ ] **Step 2: Run to verify failure** -- ModuleNotFoundError.
- [ ] **Step 3: Implement** per the Interfaces block (DuckDB path: parameterized `?` WHERE on row_id+field, mirroring the review_bundles precedent; `ledger_df` short-circuits to pandas lookup for tests).
- [ ] **Step 4: Run tests** -- all green.
- [ ] **Step 5: Commit** the two files; message: "ledger-error-classifier: verdict schema + gate-side re-derivation" + bullets.

---

### Task 3: Batch builder -- prompts + manifest, no dispatch (`scripts/ledger_error_classifier/build_dispatch.py`)

**Files:**
- Create: `scripts/ledger_error_classifier/build_dispatch.py` (+ empty `__init__.py` only if the repo's scripts subpackages have one -- mirror `scripts/agent_b2/`)
- Test: `tests/test_ledger_error_classifier_dispatch.py`

**Interfaces:**
- CLI: `python scripts/ledger_error_classifier/build_dispatch.py --batch-id <id> [--worklist <path>] [--top-n N] [--base-dir <dir>]`. Reads the provenance worklist (Task 1's output), takes top-N by priority_rank, runs `cohort_guard.check_worklist` (refuse out-of-cohort, exit 1), ensures each review_id's bundle exists (calls `review_bundles.build_review_bundles(review_ids=...)` for missing ones -- import-and-call, not editing that module), writes `data/output/ledger_error_classifier/batch/<batch_id>/`:
  - `worklist.csv` (the selected rows, PROVENANCE_WORKLIST_COLUMNS)
  - `prompts/{review_id}.md` -- scaffolding taken from B1's `bdc_cik_review.build_prompt` (read it; reuse its re-grounding/worked-example/CLI-operator structure), with lane content: the flag summary, the bundle path, the adjudication vocabulary with per-verdict requirements EXACTLY matching Task 2's validator (mechanism, culprit_citations shape, drift_fingerprint, superseding_accession, ambiguity_basis), the escalation-sibling convention, the read-only contract ("you never modify data; your output is exactly one verdict JSON at <verdict_path> or an escalation sibling"), and the gate warning ("every citation is re-derived from the provenance ledger by machinery you do not control; a citation that does not reproduce refuses the verdict").
  - `manifest_w1.json` + `manifest.json` per the Global Constraints field list, with `"grant_profile": "read_only_classifier"`, `"dispatch_requires": "admin_shell"`, and worker_read_dirs as the read-only grant list.
- Pure function core `build_batch(worklist_rows, batch_dir, ...) -> manifest_dict` so tests avoid the CLI.

- [ ] **Step 1: Write the failing tests** -- with tmp_path base-dir and a 3-row fixture worklist (2 cohort ciks + 1 out-of-cohort): (a) out-of-cohort refused (monkeypatch `cohort_guard.load_cohort_ciks` to a fixed set); (b) with cohort-only rows: batch dir contains worklist.csv + one prompt per review_id + manifest.json; (c) manifest has `dispatch_requires == "admin_shell"`, `grant_profile == "read_only_classifier"`, no `corrections_dir` key, rows[] carrying prompt_path/bundle_path/verdict_path/lock_key; (d) prompt text contains the verdict vocabulary and the verdict_path; (e) bundle-ensure calls `build_review_bundles` only for missing review_ids (monkeypatch it, assert the review_ids argument).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests** -- green.
- [ ] **Step 5: Commit**; message: "ledger-error-classifier: batch builder (prompts + manifest, no dispatch)" + bullets.

---

### Task 4: Live batch build (no dispatch), sample-leaf gate proof, docs

- [ ] **Step 1: Live artifacts (read/build only -- NO worker, NO admin shell):**

```powershell
python -m pipeline.review_queue --emit-provenance-worklist
python scripts\ledger_error_classifier\build_dispatch.py --batch-id lec_smoke_20260825 --top-n 10
```

Verify (named scratch script `scratch/2026-08-25_lec/verify_batch.py`, read-only): worklist row count == blocker-lane provenance item count; batch dir has 10 prompts + manifest; manifest cohort-clean; every referenced bundle file exists with `evidence_completeness == "source_artifact"` (rebuild bundles for any that are not).

- [ ] **Step 2: Gate proof without a worker:** extend `tests/test_ledger_error_verdict.py` with an end-to-end fixture test -- write a sample verdict leaf + one escalation sibling into tmp_path, a 2-row worklist, run `validate_dir` with a fixture ledger_df/path: one valid verdict ACCEPTED, one fabricated-citation verdict REFUSED, escalation sibling satisfies coverage. (This is the no-canary substitute: the gate is proven against hand-authored leaves.)
- [ ] **Step 3: Docs:** `docs/agent_family_architecture.md` -- mark `ledger-error-classifier` BUILT (not dispatched) with its grant profile + gate; `docs/reference/schemas.md` -- verdict-leaf schema + re-derivation gate contract + batch/manifest layout; `docs/agent_changelog.md` -- APPEND dated entry: lane built, batch `lec_smoke_20260825` prepared (counts), NO dispatch (admin shell required), the 8.6 convergence checklist ticked item-by-item, and the standing note that parser-drift verdicts' `drift_fingerprint` is the future parser-patch-author packet key.
- [ ] **Step 4: Commit docs** + the verification scratch output summary; message: "docs: ledger-error-classifier lane record (built, not dispatched)" + bullets.

---

## Self-Review Notes

- Convergence checklist coverage: (1) verdict-leaf-only output -> T2 schema; (2) escalation sibling -> T2 validate_dir + T3 prompt; (3) gate outside write reach -> `rederive_citations` runs at intake, workers get read-only grants; (4) grant profile -> manifest fields; (5) re-derivable citations -> T2 gate, proven in T4; (6) prompt scaffolding from B1 sibling, divergences in the module docstring; (7) dispatch unit = queue review_id packets, dedup already handled upstream by the 8.1 feed dedup -- noted in the changelog entry.
- Deliberate choices: NEW verdict module instead of editing dirty `verdict_leaf.py` (lane vocabulary differs; family extraction deferred per the architecture doc's own "extract when the second lane runs" rule -- this IS the second classifier lane, so note the extraction as a follow-up once dispatch experience exists); packets at queue review_id grain (cik x quarter x reason) matching bundle keying; warn-lane items excluded from packets (informational).
- No-placeholder check: validator rules, citation shape, manifest fields, prompt content requirements, and test fixtures are all specified concretely above.
- Type consistency: `ADJUDICATIONS`/`validate_ledger_verdict`/`rederive_citations`/`validate_dir`/`PROVENANCE_WORKLIST_COLUMNS`/`build_batch` names used identically across Tasks 1-4.
