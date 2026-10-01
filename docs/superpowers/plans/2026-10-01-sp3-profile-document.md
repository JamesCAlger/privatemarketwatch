# SP3 Proper: Filer Profile Document v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each of the 8 pilot filers one versioned, evidence-backed profile document (schema v1) built on Q4-2025 (2025-12-31) from the existing override files and the census, with the wrapper consolidated in as an executable section, a consistency contract between entries and the wrapper (D-precedence), and a deterministic round trip proving the documents reproduce today's override files exactly; then run the sub-project 3 exit test.

**Architecture:** Five pure modules under `scripts/profile_pilot/` plus one CLI. `profile_document.py` owns the v1 schema, admission states, stubs and `resolve`. `profile_families.py` is the spec 7.1 disposition table and a fail-closed scanner over `data/overrides`. `profile_inception.py` converts override files (knowledge -> entries or one-off corrections, executable -> wrapper blocks) and census-derived entries (the existing Stage B `profile.derive_profile`, confirmed by the next quarter) into a document. `profile_roundtrip.py` regenerates the override shapes from the documents and runs the production loaders on both trees. `profile_consistency.py` holds the consistency contract and the exit test. `profile_document_run.py` is the launcher-convention CLI; it reads the MAIN checkout's production overrides and writes only to a write-once run root. Nothing under `pipeline/` changes; no production reader is switched.

**Tech Stack:** Python 3, jsonschema (Draft 2020-12) with `referencing`, pytest through `scripts/profile_pilot/verify.py`, git (read-only `git show` for sign-off attestation).

**Spec:** `docs/superpowers/specs/2026-09-29-filer-profile-programme-design.md` sections 2.1 (D-families, D-precedence, D-corrections, D-floor, D-convention, D-winner), 3 (criteria 1 and 5), 4, 4.1, 4.2, 5 (provisional contracts), 7, 7.1, 8 row 3, 9, 10. The pilot spec v4.2 remains the authority for the envelope and census mechanics. Prior plans: `docs/superpowers/plans/2026-10-01-sp3-task0-census-published-basis.md` (Task 0/0b, predicate `census-published.v2`), `docs/superpowers/plans/2026-09-30-sp1-drift-replay.md` (replay verdicts consumed here).

## Global Constraints

- Code lives ONLY in the worktree `.claude/worktrees/filer-profile-pilot` (branch `filer-profile-pilot`); data lives in the MAIN checkout `data/` (`--data-root "<main>/data"`). The production override files read by the real run are the MAIN checkout's `data/overrides/` (production truth: e.g. the Fidelity wrapper v2, main 5b85cc4, exists only there); unit tests read only tmp fixtures and the worktree's git-tracked `data/overrides/`.
- No writes under `data/output/` or `frontend/public/data/` from any stage. No edit and no delete of any file under `data/overrides/` (main or worktree): in this sub-project the profile is additive and the override files stay the production source. Pilot writes only under `<data_root>/pilot/filer_profile/<run_id>/` (write-once roots) and `scratch/`; Task 10 may copy finished documents to the worktree's `data/profiles/`.
- No unrequested network. No `python -` and no long `python -c`. ASCII only in code, logs, docs and every written JSON (`ensure_ascii=True`).
- Tests run through the launcher, never bare pytest: `python -m scripts.profile_pilot.verify test --data-root "<main>/data" --run-id sp3p-verify-<stamp> --no-pre-backstop tests/test_profile_pilot_<x>.py`. Test files MUST match `tests/test_profile_pilot_[a-z0-9_]+.py` (the launcher refuses other targets). Use a fresh `sp3p-verify-<stamp>` run id per launcher call.
- The real run uses run ids prefixed `sp3p-profile-` (enforced by the CLI). Commit before the real run. The real run is light (JSON only, no XBRL parse) and does not take the lease, but it runs ALONE: never concurrent with pytest, `scripts/rebuild_outputs.py`, `pipeline.programme.bootstrap` or a lease-holding pilot chain (R36). The SP3 v2 re-measure chain running in the main checkout on 2026-10-01 must have exited first.
- JSON key order is behaviour: `dispatch.prefix_rules` is first-match-wins. Every comparison and hash of override content is ORDER-PRESERVING (`translate.value_sha256`), and every document and materialised override file is written WITHOUT `sort_keys` (`translate._write_once_ordered`). `paths.write_once_json` (which sorts keys) is used only for manifests and result files.
- Entries are authoritative on MEANING, the wrapper section only on PROCEDURE (D-precedence). A consistency breach blocks the filer and is resolved by superseding the wrong side with evidence, never by editing the other to match.
- Every contract attached in this sub-project carries `status_basis = "provisional"` (sub-project 2 has not reported on any kind). A detection claim is `claimed` only when the pinned SP1 replay verdict for that kind is `PASS`; otherwise `detection_not_claimed` (criterion 3).
- Rate convention storage does not change (D-convention): the `meaning.interest_rate` entry records the filer's stated convention; `interest_rate` stays the cash leg.
- Every metric reported is labelled IN-SAMPLE (Q4-2025 and Q1-2026 are signed-off, adjudicated quarters).
- SDD ledger: `.superpowers/sdd/2026-10-01-sp3-profile-document/progress.md` (create in Task 1). Subagents use model Opus 5.5; one reviewer per task.

## Non-goals (explicit)

- NO production reader flip: no module under `pipeline/` reads a profile document, and no wrapper loader is redirected. That is sub-project 4 (rate family, twin build vs the 0b base) and 6 (other families).
- NO deletion of override files, no consumer switch, no removal of `census_published.REPORTING_ENTITIES` (it becomes a code mirror checked by the consistency contract).
- NO fleet dispatch (B1/B2), no admission loop (sub-project 5), no criterion 5 pre-image check (sub-project 6: one-off corrections carry `pre_image.status = "unchecked"`).
- NO re-measure of any contract kind, no new tolerances version, no recurring-correction promotion (recurrence is FLAGGED; promotion is owner tier in sub-project 6).

## Decisions taken in this plan (the spec leaves the choice open)

| # | Question | Choice |
|---|---|---|
| P1 | How entries carry the spec 4 status set {candidate, accepted, superseded, retracted} on the Stage A envelope (statuses derived/proposed/verified/promoted/retired) | The envelope stays the bitemporal store. Admission state (candidate/accepted) lives in a per-entry `admissions` record; superseded/retracted are derived from the event log (`recorded_until` with/without a successor). `entry_state()` returns the four spec states |
| P2 | Support and confidence for inherited entries (the envelope forbids free-floating scores) | Additive envelope support kind `{"kind": "inherited_file", "path", "sha256"}`; the source file's `confidence` is copied into the admission record, never into `support` |
| P3 | `valid_from` for file-level knowledge (spec: "its date becomes valid_from") | Production applies `rate_convention`, grammars and anchors to EVERY quarter of the filer, so inherited entries get `valid_from = null`; the file's own date (`target_quarter`, `first_seen_quarter`, `updated_at`) is kept as `source_date` evidence. A file-level `valid_from = 2026-03-31` would make the resolver silent at the 2025-12-31 inception date while production uses the file |
| P4 | Point validity of one-off corrections (spec 4.2: `valid_from == valid_to == report date`) vs the envelope's half-open intervals | One-off corrections are NOT envelope entries: they live in the `corrections` section with literal `valid_from == valid_to == report_date` |
| P5 | `bdc_aggregate_row_overrides.json` (spec 7.1: partition-structure entries) and `bdc_xbrl_oracle_exceptions.json` (reconciliation-scope entry) | Both are point-dated per record, so at inception they are one-off corrections (mechanisms `aggregate_row_exclusion`, `reconciliation_scope_exception`). The same mechanism in >= 2 quarters (Ares 'Ivy Hill' 7 quarters; Stellus `rate_outliers_detected` 8 quarters; Onex 'Apryse' 2) gets a `recurrence_group` and `promotion = proposed_recurring_owner_tier`; the predicate entry is created at sign-off in sub-project 6 (D-corrections) |
| P6 | `agent_investigate_rules` | Carried whole as the second wrapper block (`agent_investigate_rules`); each rule gets an `expressibility` note (`one_off_correction` for single-quarter `row_id IN (...)` exclusions); no conversion in SP3 |
| P7 | Files the 7.1 table does not list | `bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` (mentions all 8; read by `config.UNLISTED_BDC_REFERENCE_FILE` for frontend filtering) = process artifact, excluded, owner to confirm. Any path segment after the family starting with `_`, or a `.proposed.` file = `not_loaded` (production loaders skip them, `pipeline/rule_admission.admitted`). An underscore-prefixed FAMILY (`_retired/`) = retired store, `not_loaded`. Any OTHER family that mentions a pilot CIK and has no class fails the scan (7.1: "a family added later without a class fails") |
| P8 | Inception source of the wrapper-counterpart axes (delimiter, markers, cik, entity name, fv source field) | Spec 4: the wrapper is executable, not knowledge, so these axes get census-derived entries (Q4-2025 census, `profile.derive_profile`) or stubs. A census-derived entry is `accepted` only when the Q1-2026 census derives the order-identical value (the structural tier's next-quarter confirmation, spec 6); otherwise `candidate`. The wrapper is never used to admit an entry, so the consistency contract is an independent check |
| P9 | `partition_structure.reporting_entities` (the R6 list moving out of code) | Inherited from the BCRED wrapper's `source_encodings.reporting_entity_suffixes`; `census_published.classify` gains a `reporting_entities=` argument; the module constant stays as a code mirror and the consistency contract asserts entry == wrapper == code mirror |
| P10 | Where documents live | Written to the run root `profiles/<cik>.json`; Task 10 copies them byte-identical to the worktree `data/profiles/<cik>.json` only on an exit-test PASS. A test asserts no `pipeline/` module references `data/profiles` or the profile modules |
| P11 | Consistency verdict with keys the census cannot derive | Per key: holds / breach / insufficient_evidence / not_applicable. `breach` only for an accepted entry that disagrees on an exact-compare key (`/cik`, `/invariants/fv_reconciliation/source_field`, `/source_encodings/reporting_entity_suffixes`; `/identifier_format/delimiter` compared by stripped token) or for a code mirror with no or a different entry. Representation mismatches and missing accepted entries are `insufficient_evidence` (spec 10). A filer holds iff zero breaches; insufficient keys are counted and published |

## Expected limitations (stated before the run, not tuned afterwards)

- Two filers have NO authoritative Q4-2025 census in `stageb2-sp1census-20260930t2235z`: NexPoint 0001588272 and TCW 0001715933 (`excluded.json`: `ambiguous_same_quarter_candidates`). Their census axes are `census_unavailable` stubs.
- The consistency contract is evaluated at 2025-12-31 only; the wrapper block is valid for all report dates but inception entries start at 2025-12-31 (recorded as `unevaluated` in each result).
- Under P11, "holds on all 8" can be reached largely through `insufficient_evidence` keys; the count is published beside the verdict so it cannot be read as agreement.
- The overrides in the main checkout and the worktree differ (CRLF vs LF on ~30 files; content on the Fidelity wrapper v1 vs v2). Hashes recorded as `sha256` are raw bytes of the file actually read; equality checks use the order-preserving parsed hash.

---

## File structure

| Path (worktree) | Responsibility | Task |
|---|---|---|
| `scripts/profile_pilot/envelope.py` | additive: `inherited_file` support kind; `make_assertion(..., author=, status=)` | 1 |
| `scripts/profile_pilot/schemas/filer_profile_v0.schema.json` | additive: `inherited_file` alternative in `$defs/support` | 1 |
| `scripts/profile_pilot/census_published.py` | `classify/published_positions/published_fv_sum(..., reporting_entities=None)`; constant documented as code mirror | 2 |
| `scripts/profile_pilot/schemas/filer_profile_document_v1.schema.json` (new) | document v1 layout | 3 |
| `scripts/profile_pilot/profile_document.py` (new) | grid, admission/stub constructors, `validate_document`, `entry_state`, `resolve`, `coverage`, `load_document` | 3 |
| `scripts/profile_pilot/profile_families.py` (new) | spec 7.1 table, `scan_overrides`, `collect_override_inputs` | 4 |
| `scripts/profile_pilot/profile_inception.py` (new) | wrapper blocks, corrections, inherited and census entries, stubs, `build_document` | 5, 6 |
| `scripts/profile_pilot/profile.py` | `INCEPTION_ERA` accepted by `derive_profile` | 6 |
| `scripts/profile_pilot/schemas/filer_profile_document_v0.schema.json` | `era` enum gains `inception` | 6 |
| `scripts/profile_pilot/profile_roundtrip.py` (new) | `materialise_overrides`, `expected_paths`, `roundtrip_check`, `loader_parity` | 7 |
| `scripts/profile_pilot/profile_consistency.py` (new) | `consistency_contract`, `coverage_report`, `resolver_report`, `exit_test` | 8 |
| `scripts/profile_pilot/profile_document_run.py` (new) | CLI `build` | 9 |
| `tests/test_profile_pilot_envelope.py`, `tests/test_profile_pilot_census_published.py` | appended tests | 1, 2 |
| `tests/test_profile_pilot_profile_document.py` (new) | schema/resolver tests + `minimal_document` helper | 3 |
| `tests/test_profile_pilot_profile_families.py` (new) | scanner tests + `write_tree` helper | 4 |
| `tests/test_profile_pilot_profile_inception.py` (new) | converter tests + `inception_inputs` helper | 5, 6 |
| `tests/test_profile_pilot_profile_roundtrip.py` (new) | round-trip and loader-parity tests incl. the real tracked overrides | 7 |
| `tests/test_profile_pilot_profile_consistency.py` (new) | consistency and exit-test tests | 8 |
| `tests/test_profile_pilot_profile_document_run.py` (new) | CLI tests on a fake main root | 9 |
| `docs/agent_changelog.md`, spec section 8 row 3 | records | 10 |

---

### Task 1: Envelope additive extensions (inherited support kind, author/status on assertions)

**Files:**
- Modify: `scripts/profile_pilot/envelope.py` (`_check_support`, `make_assertion`; add `SUPPORT_KINDS`, `_SHA_RE`)
- Modify: `scripts/profile_pilot/schemas/filer_profile_v0.schema.json` (`$defs/support.oneOf` gains one alternative; description sentence)
- Test: `tests/test_profile_pilot_envelope.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:

```python
SUPPORT_KINDS = ("prevalence", "context_count", "inherited_file")
def make_assertion(events: list, *, cik: str, key: str, value, valid_from: str | None, recorded_at: str,
                   support: dict, evidence: list, valid_to: str | None = None, form_type: str | None = None,
                   applies_to: dict | None = None, provenance: str = "derived", inherited_from: str | None = None,
                   author: str = "census", status: str = "derived") -> list
# support {"kind": "inherited_file", "path": <non-empty str>, "sha256": <64 lower-hex>} is admitted everywhere
```

- [ ] **Step 1: Create the SDD ledger** `.superpowers/sdd/2026-10-01-sp3-profile-document/progress.md` with header `# SP3 proper (profile document) ledger` and the line `2026-10-01 Task 1 started at <git rev-parse --short HEAD>`.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_profile_pilot_envelope.py`; `CIK`, `T0`, `_assert`, `_entry_validator`, `ev`, `EnvelopeError`, `pytest` already exist there):

```python
INHERITED = {"kind": "inherited_file", "path": "data/overrides/rate_convention/0001860424.json", "sha256": "a" * 64}
EVID_FILE = [{"kind": "override_file", "path": "data/overrides/rate_convention/0001860424.json", "sha256": "a" * 64}]


def test_inherited_file_support_with_author_and_status():
    events = ev.make_assertion([], cik=CIK, key="meaning.interest_rate", value={"convention": "all_in"},
                               valid_from=None, recorded_at=T0, support=INHERITED, evidence=EVID_FILE,
                               provenance="inherited",
                               inherited_from="data/overrides/rate_convention/0001860424.json@aaaaaaaaaaaa",
                               author="agent", status="promoted")
    [entry] = ev.materialize_entries(events)
    assert (entry["author"], entry["status"], entry["support"]) == ("agent", "promoted", INHERITED)
    assert _entry_validator().is_valid(entry)
    ev.validate_profile(events, sample_rows={})


@pytest.mark.parametrize("bad", [dict(INHERITED, path=""), dict(INHERITED, sha256="A" * 64),
                                 {"kind": "inherited_file", "path": "x"}, dict(INHERITED, extra=1)])
def test_inherited_file_support_rejects_malformed(bad):
    with pytest.raises(EnvelopeError, match="support must be"):
        _assert([], support=bad)
    [entry] = ev.materialize_entries(_assert([]))
    assert not _entry_validator().is_valid(dict(entry, support=bad))


def test_make_assertion_defaults_and_vocabulary_are_unchanged():
    [entry] = ev.materialize_entries(_assert([]))
    assert (entry["author"], entry["status"]) == ("census", "derived")
    with pytest.raises(EnvelopeError, match="author"):
        _assert([], author="robot")
    with pytest.raises(EnvelopeError, match="status"):
        _assert([], status="accepted")
```

- [ ] **Step 3: Run to fail**

Run: `python -m scripts.profile_pilot.verify test --data-root "<main>/data" --run-id sp3p-verify-t1a --no-pre-backstop tests/test_profile_pilot_envelope.py`
Expected: the new tests FAIL (`TypeError: make_assertion() got an unexpected keyword argument 'author'`; `support must be` raised for INHERITED).

- [ ] **Step 4: Implement** in `envelope.py`:

```python
SUPPORT_KINDS = ("prevalence", "context_count", "inherited_file")
_SHA_RE = re.compile(r"[0-9a-f]{64}")


def _check_support(support: Any) -> None:
    def _int(v, lo):
        return isinstance(v, int) and not isinstance(v, bool) and v >= lo
    ok = isinstance(support, dict) and (
        (support.get("kind") == "prevalence" and set(support) == {"kind", "numerator", "denominator"}
         and _int(support["numerator"], 0) and _int(support["denominator"], 1)
         and support["numerator"] <= support["denominator"])
        or (support.get("kind") == "context_count" and set(support) == {"kind", "count"}
            and _int(support["count"], 0))
        or (support.get("kind") == "inherited_file" and set(support) == {"kind", "path", "sha256"}
            and isinstance(support["path"], str) and bool(support["path"])
            and isinstance(support["sha256"], str) and bool(_SHA_RE.fullmatch(support["sha256"]))))
    if not ok:
        raise EnvelopeError("support must be {kind: prevalence, numerator, denominator}, "
                            "{kind: context_count, count} or {kind: inherited_file, path, sha256}; got "
                            + repr(support))
```

In `make_assertion` add the keyword parameters `author: str = "census", status: str = "derived"` and use them in the body (`"author": author`, `"status": status`); `_check_body` already validates both against `AUTHORS` / `STATUSES`. In the v0 schema append to `$defs/support.oneOf`:

```json
{"type": "object", "additionalProperties": false, "required": ["kind", "path", "sha256"],
 "properties": {"kind": {"const": "inherited_file"},
                "path": {"type": "string", "minLength": 1},
                "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}}
```

and extend the support description with: `inherited_file (SP3 proper): the entry's value is copied from a pinned file; the measured quantity is the file identity.`

- [ ] **Step 5: Run to pass** (`sp3p-verify-t1b`): `tests/test_profile_pilot_envelope.py tests/test_profile_pilot_profile.py tests/test_profile_pilot_translate.py` (existing v0 documents must still validate).

- [ ] **Step 6: Commit** `Add the inherited_file support kind and author/status on envelope assertions` (body: additive; v0 profiles unchanged; needed for SP3 inherited entries).

### Task 2: The reporting-entity list as an argument of the census predicate

**Files:**
- Modify: `scripts/profile_pilot/census_published.py` (`r6_reporting_entity`, `classify`, `published_positions`, `published_fv_sum`, constant comment)
- Test: `tests/test_profile_pilot_census_published.py` (append)

**Interfaces:**
- Produces:

```python
def classify(doc, *, cik, version=CENSUS_PUBLISHED_VERSION, reporting_entities=None) -> dict   # output shape unchanged
def published_positions(doc, *, cik, version=CENSUS_PUBLISHED_VERSION, reporting_entities=None) -> list
def published_fv_sum(doc, *, cik, version=CENSUS_PUBLISHED_VERSION, reporting_entities=None) -> Decimal
REPORTING_ENTITIES  # unchanged value; now the CODE MIRROR of profile entry partition_structure.reporting_entities
```

`reporting_entities=None` reads the code mirror (every existing caller; frozen v1/v2 results unchanged); a tuple (possibly empty) replaces it.

- [ ] **Step 1: Failing tests** (append; `bcred_doc`, `BCRED`, `OTHER`, `cp`, `Decimal` exist in the file):

```python
def test_r6_list_from_the_profile_replaces_the_code_mirror():
    doc = bcred_doc()
    mirror = cp.classify(doc, cik=BCRED)["rows"]
    given = cp.classify(doc, cik=BCRED, reporting_entities=("Emerald JV LP", "Verdelite JV LP"))["rows"]
    assert given == mirror
    empty = cp.classify(doc, cik=BCRED, reporting_entities=())["rows"]
    assert not any(r["underlying"] for r in empty.values())
    other = cp.classify(doc, cik=OTHER, reporting_entities=("Emerald JV LP",))["rows"]
    assert other["c1"]["underlying"] is True and other["c2"]["underlying"] is False


def test_published_fv_sum_threads_the_reporting_entities():
    doc = bcred_doc()
    assert cp.published_fv_sum(doc, cik=BCRED) == Decimal("2000000")
    assert cp.published_fv_sum(doc, cik=BCRED, reporting_entities=()) == Decimal("4000000")
    assert len(cp.published_positions(doc, cik=BCRED, reporting_entities=())) == 4
```

- [ ] **Step 2: Run to fail** (`sp3p-verify-t2a`, file `tests/test_profile_pilot_census_published.py`): `TypeError ... unexpected keyword argument 'reporting_entities'`.

- [ ] **Step 3: Implement**:

```python
# Code MIRROR of the profile entry partition_structure.reporting_entities (SP3 proper). The profile entry is
# authoritative; profile_consistency asserts entry == wrapper source_encodings == this constant. Removal is a
# consumer switch (sub-project 6/7), not done here.
REPORTING_ENTITIES = {"0001803498": ("Emerald JV LP", "Verdelite JV LP")}


def r6_reporting_entity(pos, cik, reporting_entities=None):
    source = REPORTING_ENTITIES.get(cik, ()) if reporting_entities is None else tuple(reporting_entities)
    names = {_norm(n) for n in source}
    return bool(names) and any(_norm(s) in names for s in _segments(pos["identity"].get("typed_identifier"))[1:])
```

In `classify` add the keyword `reporting_entities=None` and call `r6_reporting_entity(pos, cik, reporting_entities)`; `published_positions` and `published_fv_sum` accept the same keyword and pass it to `classify`. The output dict is unchanged.

- [ ] **Step 4: Run to pass** (`sp3p-verify-t2b`): `tests/test_profile_pilot_census_published.py tests/test_profile_pilot_totals.py tests/test_profile_pilot_contracts.py`.
- [ ] **Step 5: Commit** `Let the census predicate take the reporting-entity list from the caller`.

### Task 3: Profile document v1: schema, loader/validator, admission states, resolver

**Files:**
- Create: `scripts/profile_pilot/schemas/filer_profile_document_v1.schema.json`
- Create: `scripts/profile_pilot/profile_document.py`
- Test: `tests/test_profile_pilot_profile_document.py` (new; exports `CIK`, `NOW`, `RUN`, `minimal_document`, `one_off` for later tests)

**Interfaces:**
- Consumes: `envelope.make_assertion/materialize_entries/validate_profile/resolve_for_row/AmbiguousResolutionError/EnvelopeError` (Task 1); `census.POSITION_FIELDS/POSITION_VALUE/POSITION_RATE`.
- Produces (`scripts/profile_pilot/profile_document.py`):

```python
SCHEMA_NAME = "filer_profile_document_v1"; CONVERTER_VERSION = "profile-document.v1"
INCEPTION_REPORT_DATE = "2025-12-31"
ADMISSION_STATES = ("candidate", "accepted"); LIFECYCLE_STATES = ("candidate", "accepted", "superseded", "retracted")
ADMISSION_BASES = ("inherited_production", "census_confirmed_next_quarter", "census_unconfirmed", "adopted_predicate")
SOURCE_KINDS = ("census", "override_file", "predicate_code")
STUB_CAUSES = ("no_source", "census_unavailable", "census_stub", "candidate_pending_confirmation")
FIELD_KEYS: tuple[str, ...]   # 39 = column_contract.<23 fields> + scale_unit.<12 value/rate fields> + meaning.<4 rate fields>
FILER_KEYS: tuple[str, ...]   # 17
GRID_KEYS = FIELD_KEYS + FILER_KEYS   # 56 cells per filer
AXIS_OF_SECTION: dict[str, str]   # key section -> spec 4 semantic axis
class ProfileDocumentError(ValueError); class ProfileAmbiguityError(ProfileDocumentError)
def admission(state, basis, *, source_kind, mechanism, confidence, source_author, recorded_at, run_id, source,
              witness=None, inception_evaluation) -> dict
def stub(cik, key, cause, closing_evidence, *, entry_id=None, detail=None) -> dict
def validate_document(document: dict) -> None
def valid_at(entry: dict, report_date: str) -> bool             # half-open [valid_from, valid_to)
def entry_state(document: dict, entry_id: str) -> str          # one of LIFECYCLE_STATES
def resolve(document: dict, key: str, report_date: str, row: dict | None = None, *, as_of: str | None = None) -> dict
    # {"status": "resolved", "entry": <entry>} | {"status": "stub", "stub": <stub>} | {"status": "no_entry"}
def coverage(document: dict, report_date: str) -> dict          # key -> {"entry_ids", "accepted_entry_ids", "stub"}
def load_document(path) -> dict                                 # ascii JSON + validate_document
```

- [ ] **Step 1: Write the failing tests** (`tests/test_profile_pilot_profile_document.py`):

```python
"""SP3 proper Task 3: filer profile document v1 (schema, admission states, resolver). Pure synthetic tests."""
from __future__ import annotations

import copy
import json

import pytest

from scripts.profile_pilot import envelope
from scripts.profile_pilot import profile_document as pd

CIK = "0001901037"
NOW = "2026-10-01T12:00:00Z"
LATER = "2026-10-02T12:00:00Z"
RUN = "sp3p-profile-test"
FILE = "rate_convention/" + CIK + ".json"
Q4 = "2025-12-31"


def inherited_events(events=(), key="meaning.interest_rate", value=None, sha="b" * 64):
    path = "data/overrides/" + FILE
    return envelope.make_assertion(
        list(events), cik=CIK, key=key, value=value or {"convention": "all_in"}, valid_from=None, recorded_at=NOW,
        support={"kind": "inherited_file", "path": path, "sha256": sha},
        evidence=[{"kind": "override_file", "path": path, "sha256": sha, "value_is_file": True}],
        provenance="inherited", inherited_from=path + "@" + sha[:12], author="agent", status="promoted")


def adm(state="accepted"):
    return pd.admission(state, "inherited_production", source_kind="override_file",
                        mechanism="rate_convention override file", confidence=0.9, source_author="agent",
                        recorded_at=NOW, run_id=RUN, source="data/overrides/" + FILE,
                        inception_evaluation="none_available")


def one_off(report_date=Q4, **over):
    c = dict(correction_id=CIK + ":corr:b2:001", kind="one_off", family="agent_b2_corrections",
             mechanism="extraction_gap", fix_class="all_pik_normalization", report_date=report_date,
             valid_from=report_date, valid_to=report_date, report_dates=[report_date], target={"row_id": "ROW-1"},
             row_keyed=True, value={"cik": CIK},
             source=dict(path="agent_b2_corrections/" + CIK + "/all_pik_normalization.json", sha256="c" * 64,
                         record_index=None),
             pre_image=dict(status="unchecked", reason="criterion 5 runs in sub-project 6"),
             recurrence_group=None, promotion=None, state="accepted", admission_basis="inherited_production",
             confidence=0.9, provenance=dict(who=pd.CONVERTER_VERSION, source_author="agent", when=NOW, run_id=RUN,
                                             source="data/overrides/agent_b2_corrections"),
             recorded_at=NOW, recorded_until=None, supersedes=None)
    c.update(over)
    return c


def minimal_document(*, state="accepted", stub_all=True):
    events = inherited_events()
    entries = envelope.materialize_entries(events)
    eid = entries[0]["entry_id"]
    stubs = []
    if stub_all:
        for key in pd.GRID_KEYS:
            if key == "meaning.interest_rate":
                if state == "candidate":
                    stubs.append(pd.stub(CIK, key, "candidate_pending_confirmation", "owner sign-off of " + eid,
                                         entry_id=eid))
                continue
            stubs.append(pd.stub(CIK, key, "no_source", "a filing citation for " + key))
    return dict(schema=pd.SCHEMA_NAME, schema_version=1, document_version=1, cik=CIK,
                inception_report_date=pd.INCEPTION_REPORT_DATE, recorded_at=NOW, run_id=RUN,
                code=dict(git_head="2a218e9", converter_version=pd.CONVERTER_VERSION),
                events=events, entries=entries, admissions={eid: adm(state)}, stubs=stubs,
                wrapper_section=dict(blocks=[]), corrections=[],
                partition_predicate=dict(census_published_version="census-published.v2",
                                         published_basis_entry_id=None, reporting_entities_entry_id=None,
                                         code_mirror=dict(path="scripts/profile_pilot/census_published.py",
                                                          constant="REPORTING_ENTITIES", value=[])),
                detection_claims={}, disposition=[],
                ledger=[dict(event="document_created", at=NOW, run_id=RUN, detail={})])


def test_grid_shape():
    assert len(pd.FIELD_KEYS) == 39 and len(pd.FILER_KEYS) == 17 and len(pd.GRID_KEYS) == 56
    assert len(set(pd.GRID_KEYS)) == 56
    assert {k.split(".", 1)[0] for k in pd.GRID_KEYS} <= set(pd.AXIS_OF_SECTION)


def test_schema_enums_match_the_module_constants():
    schema = json.loads((pd.SCHEMA_DIR / pd.SCHEMA_FILE).read_text(encoding="ascii"))
    d = schema["$defs"]
    assert tuple(d["admission"]["properties"]["state"]["enum"]) == pd.ADMISSION_STATES
    assert tuple(d["admission"]["properties"]["basis"]["enum"]) == pd.ADMISSION_BASES
    assert tuple(d["admission"]["properties"]["source_kind"]["enum"]) == pd.SOURCE_KINDS
    assert tuple(d["stub"]["properties"]["cause"]["enum"]) == pd.STUB_CAUSES


def test_minimal_document_validates_and_resolves():
    doc = minimal_document()
    pd.validate_document(doc)
    hit = pd.resolve(doc, "meaning.interest_rate", Q4)
    assert hit["status"] == "resolved" and hit["entry"]["value"] == {"convention": "all_in"}
    miss = pd.resolve(doc, "scale_unit.fair_value", Q4)
    assert miss["status"] == "stub" and miss["stub"]["cause"] == "no_source"
    bare = minimal_document(stub_all=False)
    pd.validate_document(bare)
    assert pd.resolve(bare, "scale_unit.fair_value", Q4) == {"status": "no_entry"}


def test_candidates_are_invisible_to_resolve():
    doc = minimal_document(state="candidate")
    pd.validate_document(doc)
    eid = doc["entries"][0]["entry_id"]
    out = pd.resolve(doc, "meaning.interest_rate", Q4)
    assert out["status"] == "stub" and out["stub"]["entry_id"] == eid
    assert pd.entry_state(doc, eid) == "candidate"
    cov = pd.coverage(doc, Q4)["meaning.interest_rate"]
    assert cov["entry_ids"] == [eid] and cov["accepted_entry_ids"] == []


def test_entry_state_superseded_and_retracted():
    doc = minimal_document()
    eid = doc["entries"][0]["entry_id"]
    events = envelope.append_correction(doc["events"], eid, value={"convention": "cash"}, recorded_at=LATER,
                                        evidence=[{"kind": "owner_ruling", "ref": "R99"}],
                                        support={"kind": "context_count", "count": 1})
    corrected = dict(doc, events=events, entries=envelope.materialize_entries(events))
    new = [e["entry_id"] for e in corrected["entries"] if e["entry_id"] != eid][0]
    corrected["admissions"] = dict(doc["admissions"], **{new: adm()})
    pd.validate_document(corrected)
    assert pd.entry_state(corrected, eid) == "superseded" and pd.entry_state(corrected, new) == "accepted"
    retract = doc["events"] + [{"event": "retract", "event_id": "retract:" + eid, "entry_id": eid,
                                "recorded_at": LATER}]
    gone = dict(doc, events=retract, entries=envelope.materialize_entries(retract))
    pd.validate_document(gone)
    assert pd.entry_state(gone, eid) == "retracted"


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(admissions={}), "admissions"),
    (lambda d: d["stubs"].append(dict(d["stubs"][0])), "one stub per key"),
    (lambda d: d["stubs"].append(pd.stub(CIK, "meaning.interest_rate", "no_source", "x")), "accepted entry"),
    (lambda d: d.update(entries=[]), "materialized view"),
    (lambda d: d.update(corrections=[one_off(valid_to="2026-03-31")]), "one_off"),
    (lambda d: d.update(corrections=[one_off(), one_off()]), "correction ids"),
    (lambda d: d.update(schema="filer_profile_document_v0"), "schema"),
])
def test_validate_rejects(mutate, message):
    doc = copy.deepcopy(minimal_document())
    mutate(doc)
    with pytest.raises(pd.ProfileDocumentError, match=message):
        pd.validate_document(doc)


def test_unknown_stub_key_is_refused_at_construction():
    with pytest.raises(pd.ProfileDocumentError):
        pd.stub(CIK, "not_a_grid.key", "no_source", "x")


def test_equally_specific_accepted_entries_raise_ambiguity():
    events = inherited_events(inherited_events(), value={"convention": "cash"})
    entries = envelope.materialize_entries(events)
    doc = dict(minimal_document(), events=events, entries=entries,
               admissions={e["entry_id"]: adm() for e in entries})
    with pytest.raises(pd.ProfileAmbiguityError):
        pd.resolve(doc, "meaning.interest_rate", Q4)


def test_load_document_round_trips(tmp_path):
    doc = minimal_document()
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    assert pd.load_document(path) == doc
```

- [ ] **Step 2: Run to fail** (`sp3p-verify-t3a`, `tests/test_profile_pilot_profile_document.py`): `ModuleNotFoundError: scripts.profile_pilot.profile_document`.

- [ ] **Step 3: Write the schema** `scripts/profile_pilot/schemas/filer_profile_document_v1.schema.json` (ASCII):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "filer_profile_document_v1.schema.json",
  "title": "Filer profile document v1 (filer-profile programme spec section 4; SP3 proper)",
  "description": "One document per filer. events/entries are the Stage A envelope (filer_profile_v0.schema.json, entry contract unchanged except the additive inherited_file support kind); entries is the materialized view of events. admissions carry the spec 4 admission state (candidate|accepted); superseded and retracted are derived from the event log. stubs are explicit insufficient-evidence records per grid key with the evidence that would close them. wrapper_section holds the executable blocks (D-consolidate); corrections holds section 4.2 corrections (one-off: valid_from == valid_to == report_date). Nothing but the wrapper section is executable.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "schema_version", "document_version", "cik", "inception_report_date", "recorded_at",
               "run_id", "code", "events", "entries", "admissions", "stubs", "wrapper_section", "corrections",
               "partition_predicate", "detection_claims", "disposition", "ledger"],
  "properties": {
    "schema": {"const": "filer_profile_document_v1"},
    "schema_version": {"const": 1},
    "document_version": {"type": "integer", "minimum": 1},
    "cik": {"type": "string", "pattern": "^[0-9]{10}$"},
    "inception_report_date": {"$ref": "#/$defs/date"},
    "recorded_at": {"$ref": "#/$defs/ts"},
    "run_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,79}$"},
    "code": {"type": "object", "additionalProperties": false, "required": ["git_head", "converter_version"],
             "properties": {"git_head": {"type": "string", "minLength": 7},
                            "converter_version": {"type": "string", "minLength": 1}}},
    "events": {"type": "array", "items": {"$ref": "#/$defs/event"}},
    "entries": {"type": "array", "items": {"$ref": "filer_profile_v0.schema.json#/$defs/entry"}},
    "admissions": {"type": "object", "additionalProperties": {"$ref": "#/$defs/admission"}},
    "stubs": {"type": "array", "items": {"$ref": "#/$defs/stub"}},
    "wrapper_section": {"type": "object", "additionalProperties": false, "required": ["blocks"],
                        "properties": {"blocks": {"type": "array", "items": {"$ref": "#/$defs/block"}}}},
    "corrections": {"type": "array", "items": {"$ref": "#/$defs/correction"}},
    "partition_predicate": {
      "type": "object", "additionalProperties": false,
      "required": ["census_published_version", "published_basis_entry_id", "reporting_entities_entry_id", "code_mirror"],
      "properties": {
        "census_published_version": {"type": "string", "minLength": 1},
        "published_basis_entry_id": {"type": ["string", "null"], "minLength": 1},
        "reporting_entities_entry_id": {"type": ["string", "null"], "minLength": 1},
        "code_mirror": {"type": "object", "additionalProperties": false, "required": ["path", "constant", "value"],
                        "properties": {"path": {"type": "string", "minLength": 1},
                                       "constant": {"type": "string", "minLength": 1},
                                       "value": {"type": "array", "items": {"type": "string"}}}}}},
    "detection_claims": {"type": "object", "additionalProperties": {
      "type": "object", "additionalProperties": false, "required": ["claim", "verdict", "replay_run_id"],
      "properties": {"claim": {"enum": ["claimed", "detection_not_claimed"]},
                     "verdict": {"type": "string", "minLength": 1},
                     "replay_run_id": {"type": "string", "minLength": 1}}}},
    "disposition": {"type": "array", "items": {"$ref": "#/$defs/disposition"}},
    "ledger": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/ledger_event"}}
  },
  "$defs": {
    "date": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
    "opt_date": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/date"}]},
    "ts": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"},
    "opt_ts": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/ts"}]},
    "sha": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "event": {"type": "object", "required": ["event", "event_id", "entry_id", "recorded_at"],
              "properties": {"event": {"enum": ["assert", "retract"]}}},
    "provenance": {"type": "object", "additionalProperties": false,
                   "required": ["who", "source_author", "when", "run_id", "source"],
                   "properties": {"who": {"type": "string", "minLength": 1},
                                  "source_author": {"type": "string", "minLength": 1},
                                  "when": {"$ref": "#/$defs/ts"},
                                  "run_id": {"type": "string", "minLength": 1},
                                  "source": {"type": "string", "minLength": 1}}},
    "admission": {"type": "object", "additionalProperties": false,
                  "required": ["state", "basis", "source_kind", "mechanism", "confidence", "provenance", "witness",
                               "contract"],
                  "properties": {
                    "state": {"enum": ["candidate", "accepted"]},
                    "basis": {"enum": ["inherited_production", "census_confirmed_next_quarter", "census_unconfirmed",
                                       "adopted_predicate"]},
                    "source_kind": {"enum": ["census", "override_file", "predicate_code"]},
                    "mechanism": {"type": "string", "minLength": 1},
                    "confidence": {"type": ["number", "null"]},
                    "provenance": {"$ref": "#/$defs/provenance"},
                    "witness": {"type": "object"},
                    "contract": {"type": "object", "additionalProperties": false,
                                 "required": ["status_basis", "inception_evaluation"],
                                 "properties": {"status_basis": {"const": "provisional"},
                                                "inception_evaluation": {"type": "string", "minLength": 1}}}}},
    "stub": {"type": "object", "additionalProperties": false,
             "required": ["stub_id", "key", "cause", "closing_evidence", "entry_id", "detail"],
             "properties": {"stub_id": {"type": "string", "minLength": 1},
                            "key": {"type": "string", "pattern": "^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)*$"},
                            "cause": {"enum": ["no_source", "census_unavailable", "census_stub",
                                               "candidate_pending_confirmation"]},
                            "closing_evidence": {"type": "string", "minLength": 1},
                            "entry_id": {"type": ["string", "null"], "minLength": 1},
                            "detail": {"type": "object"}}},
    "block": {"type": "object", "additionalProperties": false,
              "required": ["block_id", "family", "version", "content", "content_sha256", "source_files", "valid_from",
                           "valid_to", "recorded_at", "recorded_until", "supersedes", "supersession_kind",
                           "attested_under", "evidence", "expressibility"],
              "properties": {
                "block_id": {"type": "string", "minLength": 1},
                "family": {"enum": ["bdc_xbrl_wrapper", "agent_investigate_rules"]},
                "version": {"type": "integer", "minimum": 1},
                "content": {"type": "object"},
                "content_sha256": {"$ref": "#/$defs/sha"},
                "source_files": {"type": "array", "minItems": 1, "items": {
                  "type": "object", "additionalProperties": false, "required": ["path", "sha256", "ordered_sha256"],
                  "properties": {"path": {"type": "string", "minLength": 1}, "sha256": {"$ref": "#/$defs/sha"},
                                 "ordered_sha256": {"$ref": "#/$defs/sha"}}}},
                "valid_from": {"$ref": "#/$defs/opt_date"},
                "valid_to": {"$ref": "#/$defs/opt_date"},
                "recorded_at": {"$ref": "#/$defs/ts"},
                "recorded_until": {"$ref": "#/$defs/opt_ts"},
                "supersedes": {"type": ["string", "null"], "minLength": 1},
                "supersession_kind": {"enum": [null, "correction", "change"]},
                "attested_under": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "evidence": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["kind"]}},
                "expressibility": {"type": ["object", "null"]}}},
    "correction": {"type": "object", "additionalProperties": false,
                   "required": ["correction_id", "kind", "family", "mechanism", "fix_class", "report_date",
                                "valid_from", "valid_to", "report_dates", "target", "row_keyed", "value", "source",
                                "pre_image", "recurrence_group", "promotion", "state", "admission_basis",
                                "confidence", "provenance", "recorded_at", "recorded_until", "supersedes"],
                   "properties": {
                     "correction_id": {"type": "string", "minLength": 1},
                     "kind": {"enum": ["one_off", "multi_quarter", "undated"]},
                     "family": {"type": "string", "minLength": 1},
                     "mechanism": {"type": "string", "minLength": 1},
                     "fix_class": {"type": ["string", "null"]},
                     "report_date": {"$ref": "#/$defs/opt_date"},
                     "valid_from": {"$ref": "#/$defs/opt_date"},
                     "valid_to": {"$ref": "#/$defs/opt_date"},
                     "report_dates": {"type": "array", "items": {"$ref": "#/$defs/date"}},
                     "target": {"type": "object"},
                     "row_keyed": {"type": "boolean"},
                     "value": {"type": "object"},
                     "source": {"type": "object", "additionalProperties": false,
                                "required": ["path", "sha256", "record_index"],
                                "properties": {"path": {"type": "string", "minLength": 1},
                                               "sha256": {"$ref": "#/$defs/sha"},
                                               "record_index": {"type": ["integer", "null"], "minimum": 0}}},
                     "pre_image": {"type": "object", "additionalProperties": false, "required": ["status", "reason"],
                                   "properties": {"status": {"enum": ["unchecked", "holds", "changed", "row_gone"]},
                                                  "reason": {"type": "string", "minLength": 1}}},
                     "recurrence_group": {"type": ["string", "null"], "minLength": 1},
                     "promotion": {"enum": [null, "proposed_recurring_owner_tier"]},
                     "state": {"enum": ["candidate", "accepted", "superseded", "retracted"]},
                     "admission_basis": {"type": "string", "minLength": 1},
                     "confidence": {"type": ["number", "null"]},
                     "provenance": {"$ref": "#/$defs/provenance"},
                     "recorded_at": {"$ref": "#/$defs/ts"},
                     "recorded_until": {"$ref": "#/$defs/opt_ts"},
                     "supersedes": {"type": ["string", "null"], "minLength": 1}}},
    "disposition": {"type": "object", "additionalProperties": false,
                    "required": ["path", "family", "cls", "action", "sha256", "ordered_sha256", "targets", "reason",
                                 "record_indexes"],
                    "properties": {
                      "path": {"type": "string", "minLength": 1},
                      "family": {"type": "string", "minLength": 1},
                      "cls": {"enum": ["knowledge", "executable", "process_artifact", "not_applicable"]},
                      "action": {"enum": ["entry", "correction", "wrapper_block", "excluded", "not_loaded",
                                          "foreign_mention"]},
                      "sha256": {"$ref": "#/$defs/sha"},
                      "ordered_sha256": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/sha"}]},
                      "targets": {"type": "array", "items": {"type": "string", "minLength": 1}},
                      "reason": {"type": ["string", "null"]},
                      "record_indexes": {"type": ["array", "null"], "items": {"type": "integer", "minimum": 0}}}},
    "ledger_event": {"type": "object", "additionalProperties": false, "required": ["event", "at", "run_id", "detail"],
                     "properties": {"event": {"type": "string", "minLength": 1}, "at": {"$ref": "#/$defs/ts"},
                                    "run_id": {"type": "string", "minLength": 1}, "detail": {"type": "object"}}}
  }
}
```

- [ ] **Step 4: Implement** `scripts/profile_pilot/profile_document.py`:

```python
"""SP3 proper: the filer profile document v1 (programme spec section 4).

One document per filer, layered over the Stage A envelope (scripts/profile_pilot/envelope.py), which stays the
bitemporal entry store and resolver: `events` is the append-only log and `entries` its materialized view. v1 adds
`admissions` (spec 4 admission state per entry; confidence copied from the source file, never a support; contract
status_basis always "provisional" in SP3), `stubs` (one explicit insufficient-evidence stub per grid key without an
accepted entry, with the evidence that would close it: criterion 1), `wrapper_section` (executable blocks,
D-consolidate), `corrections` (spec 4.2; one-off: valid_from == valid_to == report_date, outside the envelope because
envelope intervals are half-open), `partition_predicate`, `detection_claims`, `disposition` (spec 7.1 file mapping) and
a `ledger`.

entry_state() returns the four spec states: accepted/candidate from the admission record, superseded/retracted from
the event log. resolve() answers only from ACCEPTED entries; a key without one answers with its stub; equally
specific accepted entries raise ProfileAmbiguityError. Pure except reading the JSON Schemas and load_document().
"""
from __future__ import annotations

import copy
from functools import lru_cache
import json
from pathlib import Path

from scripts.profile_pilot import envelope
from scripts.profile_pilot.census import POSITION_FIELDS, POSITION_RATE, POSITION_VALUE

SCHEMA_NAME = "filer_profile_document_v1"
SCHEMA_FILE = "filer_profile_document_v1.schema.json"
ENTRY_SCHEMA_FILE = "filer_profile_v0.schema.json"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
CONVERTER_VERSION = "profile-document.v1"
INCEPTION_REPORT_DATE = "2025-12-31"
ADMISSION_STATES = ("candidate", "accepted")
LIFECYCLE_STATES = ("candidate", "accepted", "superseded", "retracted")
ADMISSION_BASES = ("inherited_production", "census_confirmed_next_quarter", "census_unconfirmed", "adopted_predicate")
SOURCE_KINDS = ("census", "override_file", "predicate_code")
STUB_CAUSES = ("no_source", "census_unavailable", "census_stub", "candidate_pending_confirmation")

# The coverage grid of criterion 1: per-field axes, then filer-level keys. Key names reuse the Stage B census keys
# where the census derives the axis (column_contract.* = source concept set), so census entries land on the grid.
FIELD_KEYS = (tuple("column_contract." + f for f in POSITION_FIELDS)
              + tuple("scale_unit." + f for f in POSITION_VALUE + POSITION_RATE)
              + tuple("meaning." + f for f in POSITION_RATE))
FILER_KEYS = ("identifier_format.delimiter", "identifier_format.alternate_delimiters",
              "identifier_format.field_order", "identifier_format.dialect", "identifier_format.anchors",
              "subtotals_and_headings.aggregate_labels", "subtotals_and_headings.non_private_markers",
              "subtotals_and_headings.prefix_rules",
              "fund_level_concepts.entity_cik", "fund_level_concepts.entity_registrant_name",
              "fund_level_concepts.investments_at_fair_value_concept",
              "partition_structure.published_basis", "partition_structure.reporting_entities",
              "income_proofs.principal_currency", "income_proofs.rate_units", "income_proofs.duration",
              "income_proofs.estimated_income_calibration")
GRID_KEYS = FIELD_KEYS + FILER_KEYS
AXIS_OF_SECTION = {"column_contract": "source_concept_set", "fund_level_concepts": "source_concept_set",
                   "scale_unit": "scale_and_unit", "meaning": "meaning",
                   "identifier_format": "identifier_format_and_dialect",
                   "subtotals_and_headings": "partition_structure", "partition_structure": "partition_structure",
                   "income_proofs": "income_proofs"}


class ProfileDocumentError(ValueError):
    """A profile document violates its schema or the v1 document contract."""


class ProfileAmbiguityError(ProfileDocumentError):
    """Two equally specific ACCEPTED entries answer one key for one row and report date."""


def admission(state, basis, *, source_kind, mechanism, confidence, source_author, recorded_at, run_id, source,
              witness=None, inception_evaluation) -> dict:
    if state not in ADMISSION_STATES or basis not in ADMISSION_BASES or source_kind not in SOURCE_KINDS:
        raise ProfileDocumentError("bad admission " + repr((state, basis, source_kind)))
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = None
    return dict(state=state, basis=basis, source_kind=source_kind, mechanism=mechanism, confidence=confidence,
                provenance=dict(who=CONVERTER_VERSION, source_author=source_author, when=recorded_at,
                                run_id=run_id, source=source),
                witness=dict(witness or {}),
                contract=dict(status_basis="provisional", inception_evaluation=inception_evaluation))


def stub(cik, key, cause, closing_evidence, *, entry_id=None, detail=None) -> dict:
    if key not in GRID_KEYS or cause not in STUB_CAUSES or not closing_evidence:
        raise ProfileDocumentError("bad stub " + repr((key, cause, closing_evidence)))
    return dict(stub_id=cik + ":stub:" + key, key=key, cause=cause, closing_evidence=closing_evidence,
                entry_id=entry_id, detail=dict(detail or {}))


@lru_cache(maxsize=1)
def _validator():
    import jsonschema
    from referencing import Registry, Resource
    document = json.loads((SCHEMA_DIR / SCHEMA_FILE).read_text(encoding="ascii"))
    entry = json.loads((SCHEMA_DIR / ENTRY_SCHEMA_FILE).read_text(encoding="ascii"))
    registry = Registry().with_resources([(ENTRY_SCHEMA_FILE, Resource.from_contents(entry)),
                                          (SCHEMA_FILE, Resource.from_contents(document))])
    return jsonschema.Draft202012Validator(document, registry=registry)


def valid_at(entry: dict, report_date: str) -> bool:
    """Half-open valid interval [valid_from, valid_to) of an envelope entry contains report_date."""
    lo, hi = entry["valid_from"], entry["valid_to"]
    return (lo is None or lo <= report_date) and (hi is None or report_date < hi)


def _live(document: dict, report_date: str) -> list:
    return [e for e in envelope.materialize_entries(document["events"])
            if e["recorded_until"] is None and valid_at(e, report_date)]


def validate_document(document: dict) -> None:
    errors = sorted(_validator().iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        raise ProfileDocumentError("schema: " + "/".join(map(str, errors[0].absolute_path)) + ": "
                                   + errors[0].message[:300])
    try:
        envelope.validate_profile(document["events"], sample_rows={})
    except envelope.EnvelopeError as exc:
        raise ProfileDocumentError(str(exc)) from exc
    materialized = envelope.materialize_entries(document["events"])
    if materialized != document["entries"]:
        raise ProfileDocumentError("entries are not the materialized view of the event log")
    ids = {e["entry_id"] for e in materialized}
    if set(document["admissions"]) != ids:
        raise ProfileDocumentError("admissions must cover exactly the entries: "
                                   + repr(sorted(ids ^ set(document["admissions"]))[:5]))
    foreign = [i for i in ids if not i.startswith(document["cik"] + ":")]
    if foreign:
        raise ProfileDocumentError("entries of another filer: " + repr(foreign[:5]))
    keys = [s["key"] for s in document["stubs"]]
    if len(keys) != len(set(keys)):
        raise ProfileDocumentError("one stub per key")
    for s in document["stubs"]:
        if s["key"] not in GRID_KEYS:
            raise ProfileDocumentError("stub for a key outside the grid: " + s["key"])
        if s["entry_id"] is not None and s["entry_id"] not in ids:
            raise ProfileDocumentError("stub names an unknown entry: " + s["entry_id"])
    accepted = {e["key"] for e in _live(document, document["inception_report_date"])
                if document["admissions"][e["entry_id"]]["state"] == "accepted"}
    clash = sorted(set(keys) & accepted)
    if clash:
        raise ProfileDocumentError("stub for a key that has an accepted entry: " + repr(clash[:5]))
    blocks = [b["block_id"] for b in document["wrapper_section"]["blocks"]]
    if len(blocks) != len(set(blocks)):
        raise ProfileDocumentError("block ids must be unique")
    for b in document["wrapper_section"]["blocks"]:
        if b["supersedes"] is not None and b["supersedes"] not in blocks:
            raise ProfileDocumentError("block supersedes an unknown block: " + b["supersedes"])
    corr = [c["correction_id"] for c in document["corrections"]]
    if len(corr) != len(set(corr)):
        raise ProfileDocumentError("correction ids must be unique")
    for c in document["corrections"]:
        if c["kind"] == "one_off" and not (c["report_date"] and c["valid_from"] == c["valid_to"] == c["report_date"]
                                           and c["report_dates"] == [c["report_date"]]):
            raise ProfileDocumentError("one_off correction must have valid_from == valid_to == report_date: "
                                       + c["correction_id"])


def entry_state(document: dict, entry_id: str) -> str:
    entries = {e["entry_id"]: e for e in envelope.materialize_entries(document["events"])}
    if entry_id not in entries:
        raise ProfileDocumentError("unknown entry " + repr(entry_id))
    if entries[entry_id]["recorded_until"] is not None:
        return ("superseded" if any(e["supersedes"] == entry_id for e in entries.values()) else "retracted")
    return document["admissions"][entry_id]["state"]


def resolve(document: dict, key: str, report_date: str, row: dict | None = None, *, as_of: str | None = None) -> dict:
    entries = envelope.materialize_entries(document["events"], as_of)
    accepted = [e for e in entries if document["admissions"][e["entry_id"]]["state"] == "accepted"]
    try:
        found = envelope.resolve_for_row(accepted, row or {}, key, report_date, None, as_of)
    except envelope.AmbiguousResolutionError as exc:
        raise ProfileAmbiguityError(str(exc)) from exc
    if found.found:
        return {"status": "resolved", "entry": found.entry}
    hit = next((s for s in document["stubs"] if s["key"] == key), None)
    if hit is not None:
        return {"status": "stub", "stub": copy.deepcopy(hit)}
    return {"status": "no_entry"}


def coverage(document: dict, report_date: str) -> dict:
    live = _live(document, report_date)
    stubs = {s["key"]: s for s in document["stubs"]}
    out = {}
    for key in GRID_KEYS:
        mine = [e for e in live if e["key"] == key]
        out[key] = dict(entry_ids=[e["entry_id"] for e in mine],
                        accepted_entry_ids=[e["entry_id"] for e in mine
                                            if document["admissions"][e["entry_id"]]["state"] == "accepted"],
                        stub=copy.deepcopy(stubs.get(key)))
    return out


def load_document(path) -> dict:
    document = json.loads(Path(path).read_text(encoding="ascii"))
    validate_document(document)
    return document
```

- [ ] **Step 5: Run to pass** (`sp3p-verify-t3b`, `tests/test_profile_pilot_profile_document.py tests/test_profile_pilot_envelope.py`).
- [ ] **Step 6: Commit** `Add the filer profile document v1 schema, validator and resolver`.

### Task 4: Override-family disposition table and fail-closed scanner

**Files:**
- Create: `scripts/profile_pilot/profile_families.py`
- Test: `tests/test_profile_pilot_profile_families.py` (new; exports `write_tree`, `PILOT`, `wrapper_v3`, `ARES`, `STELLUS`)

**Interfaces:**
- Consumes: `translate.value_sha256` (order-preserving hash).
- Produces:

```python
REPO_PREFIX = "data/overrides/"
CLASSES = ("knowledge", "executable", "process_artifact", "not_applicable")
ACTIONS = ("entry", "correction", "wrapper_block", "excluded", "not_loaded", "foreign_mention")
SHARED_FILES = ("bdc_aggregate_row_overrides.json", "bdc_xbrl_oracle_exceptions.json")
FAMILY_CLASSES: dict[str, dict]   # family -> {"cls", "action", "reason"} (spec 7.1 table; action may be "must_be_absent")
FILE_CLASSES: dict[str, dict]     # exact relative path -> same shape (P7)
MAX_SCAN_BYTES = 20_000_000
class FamilyError(ValueError)
def cik10(value) -> str | None
def read_json(path) -> object                       # utf-8-sig, as production loaders read
def raw_sha256(path) -> str
def family_of(relative: str) -> str
def owner_cik(relative: str) -> str | None
def is_loaded(relative: str) -> bool
def classify_path(relative: str) -> dict | None
def scan_overrides(root: Path, ciks) -> list[dict]
    # hits: {"path", "family", "cls", "action", "ciks": [cik10...], "owner": cik10|None, "reason"}
def collect_override_inputs(root: Path, cik: str, hits: list[dict]) -> dict
    # {"files": {family: [{"path", "sha256", "content"}]}, "shared": {name: {"sha256", "records": [[index, record]]}},
    #  "disposition": [disposition records, schema $defs/disposition, targets empty]}
```

- [ ] **Step 1: Failing tests** (`tests/test_profile_pilot_profile_families.py`):

```python
"""SP3 proper Task 4: spec 7.1 override-family disposition and the fail-closed scanner. tmp_path trees only."""
from __future__ import annotations

import json

import pytest

from scripts.profile_pilot import profile_families as pf

ARES, STELLUS, BCRED = "0001287750", "0001901037", "0001803498"
PILOT = (ARES, STELLUS, BCRED)


def write_tree(root, files):
    for rel, value in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = value if isinstance(value, str) else json.dumps(value, indent=2)
        path.write_text(text, encoding="utf-8")
    return root


def wrapper_v3(cik, **extra):
    body = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": cik, "entity_name": "Fund " + cik, "version": 1,
            "source": "bdc_xbrl",
            "dispatch": {"rule_prefix": "F" + cik[-4:], "prefix_rules": {"Second Lien": "debt", "First Lien": "debt"},
                         "aggregate_markers": ["total investments"]},
            "identifier_format": {"delimiter": " | "}}
    body.update(extra)
    return body


def base_tree(tmp_path):
    return write_tree(tmp_path / "overrides", {
        "bdc_xbrl_wrappers/" + ARES + ".json": wrapper_v3(ARES),
        "bdc_xbrl_wrappers/0009999999.json": wrapper_v3("0009999999"),
        "bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json": {"entries": [{"cik": ARES}]},
        "rate_convention/" + STELLUS + ".json": {"cik": STELLUS, "convention": "all_in", "target_quarter": "2026-03-31"},
        "agent_b2_corrections/" + ARES + "/comparative_period_filter.json":
            {"cik": ARES, "mechanism": "comparative_leak", "fix_class": "comparative_period_filter",
             "template": {"report_date": "2025-12-31"}},
        "agent_b2_corrections/" + ARES + "/_pulled_x_20260821/all_pik_normalization.json": {"cik": ARES},
        "agent_investigate_rules/1287750/exclude_x.json": {"cik": "1287750", "rule_id": "exclude_x"},
        "agent_investigate_rules/1803498/_retired_y.json": {"cik": "1803498"},
        "agent_anchor/1287750/2026-03-31.json": {"cik": "1287750"},
        "bdc_aggregate_row_overrides.json": {"overrides": [
            {"cik": "0001287032", "report_date": "2022-12-31", "match_text": "A"},
            {"cik": ARES, "report_date": "2025-09-30", "match_text": "Ivy Hill Asset Management, L.P."},
            {"cik": ARES, "report_date": "2025-12-31", "match_text": "Ivy Hill Asset Management, L.P."}]},
        "bdc_xbrl_oracle_exceptions.json": [{"cik": STELLUS, "report_date": "2025-12-31",
                                             "oracle_reason": "rate_outliers_detected", "confidence": 0.90}],
        "identifier_spread_corrections.json": {"corrections": [{"cik": "0001234567", "fv": 1287750}]},
        "conservation_scope/other.json": {"cik": "0001111111"}})


def test_scan_classifies_every_hit(tmp_path):
    hits = {h["path"]: h for h in pf.scan_overrides(base_tree(tmp_path), PILOT)}
    assert hits["bdc_xbrl_wrappers/" + ARES + ".json"]["action"] == "wrapper_block"
    assert hits["bdc_xbrl_wrappers/" + ARES + ".json"]["owner"] == ARES
    assert hits["bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json"]["action"] == "excluded"
    assert hits["rate_convention/" + STELLUS + ".json"]["action"] == "entry"
    assert hits["agent_b2_corrections/" + ARES + "/comparative_period_filter.json"]["action"] == "correction"
    assert hits["agent_b2_corrections/" + ARES + "/_pulled_x_20260821/all_pik_normalization.json"]["action"] == "not_loaded"
    assert hits["agent_investigate_rules/1287750/exclude_x.json"]["owner"] == ARES
    assert hits["agent_investigate_rules/1803498/_retired_y.json"]["action"] == "not_loaded"
    assert hits["agent_anchor/1287750/2026-03-31.json"]["action"] == "excluded"
    assert hits["bdc_aggregate_row_overrides.json"]["ciks"] == [ARES] and hits["bdc_aggregate_row_overrides.json"]["owner"] is None
    assert "bdc_xbrl_wrappers/0009999999.json" not in hits
    assert "identifier_spread_corrections.json" not in hits   # 1287750 as a JSON number is not a mention


def test_unclassified_family_with_a_pilot_mention_fails_closed(tmp_path):
    root = base_tree(tmp_path)
    write_tree(root, {"brand_new_family/x.json": {"cik": ARES}})
    with pytest.raises(pf.FamilyError, match="unclassified"):
        pf.scan_overrides(root, PILOT)


def test_must_be_absent_family_with_a_pilot_mention_fails(tmp_path):
    root = base_tree(tmp_path)
    write_tree(root, {"identifier_spread_corrections.json": {"corrections": [{"cik": ARES}]}})
    with pytest.raises(pf.FamilyError, match="must not mention"):
        pf.scan_overrides(root, PILOT)


def test_collect_override_inputs_splits_files_shared_and_disposition(tmp_path):
    root = base_tree(tmp_path)
    hits = pf.scan_overrides(root, PILOT)
    ares = pf.collect_override_inputs(root, ARES, hits)
    assert [f["path"] for f in ares["files"]["bdc_xbrl_wrappers"]] == ["bdc_xbrl_wrappers/" + ARES + ".json"]
    assert ares["files"]["bdc_xbrl_wrappers"][0]["content"]["dispatch"]["prefix_rules"] == \
        {"Second Lien": "debt", "First Lien": "debt"}
    assert list(ares["files"]["bdc_xbrl_wrappers"][0]["content"]["dispatch"]["prefix_rules"]) == \
        ["Second Lien", "First Lien"]
    assert [i for i, _ in ares["shared"]["bdc_aggregate_row_overrides.json"]["records"]] == [1, 2]
    actions = {d["path"]: d["action"] for d in ares["disposition"]}
    assert actions["agent_anchor/1287750/2026-03-31.json"] == "excluded"
    assert actions["agent_b2_corrections/" + ARES + "/_pulled_x_20260821/all_pik_normalization.json"] == "not_loaded"
    assert all(len(d["sha256"]) == 64 and d["targets"] == [] for d in ares["disposition"])
    stellus = pf.collect_override_inputs(root, STELLUS, hits)
    assert stellus["shared"]["bdc_xbrl_oracle_exceptions.json"]["records"][0][0] == 0
    assert "bdc_xbrl_wrappers" not in stellus["files"]


def test_foreign_owner_is_recorded_not_converted(tmp_path):
    root = base_tree(tmp_path)
    write_tree(root, {"bdc_xbrl_wrappers/0009999999.json": wrapper_v3("0009999999", note="peer of 0001287750")})
    hits = pf.scan_overrides(root, PILOT)
    ares = pf.collect_override_inputs(root, ARES, hits)
    row = next(d for d in ares["disposition"] if d["path"] == "bdc_xbrl_wrappers/0009999999.json")
    assert row["action"] == "foreign_mention"
    assert [f["path"] for f in ares["files"]["bdc_xbrl_wrappers"]] == ["bdc_xbrl_wrappers/" + ARES + ".json"]


def test_shared_mention_outside_a_record_cik_is_foreign(tmp_path):
    root = base_tree(tmp_path)
    write_tree(root, {"bdc_xbrl_oracle_exceptions.json": [
        {"cik": "0001111111", "report_date": "2025-12-31", "oracle_reason": "x", "evidence": "see 0001287750-23-1"}]})
    hits = pf.scan_overrides(root, PILOT)
    ares = pf.collect_override_inputs(root, ARES, hits)
    row = next(d for d in ares["disposition"] if d["path"] == "bdc_xbrl_oracle_exceptions.json")
    assert row["action"] == "foreign_mention" and "bdc_xbrl_oracle_exceptions.json" not in ares["shared"]


def test_helpers():
    assert pf.cik10("1287750") == ARES and pf.cik10(None) is None
    assert pf.owner_cik("agent_investigate_rules/1715933/1715933_twin_star.json") == "0001715933"
    assert pf.owner_cik("bdc_aggregate_row_overrides.json") is None
    assert pf.is_loaded("agent_investigate_rules/1803498/_retired_y.json") is False
    assert pf.is_loaded("agent_b2_corrections/0001287750/x.proposed.json") is False
    assert pf.is_loaded("rate_convention/0001860424.json") is True
```

- [ ] **Step 2: Run to fail** (`sp3p-verify-t4a`).

- [ ] **Step 3: Implement** `scripts/profile_pilot/profile_families.py`:

```python
"""SP3 proper: the spec 7.1 override-family disposition table and the scanner that applies it.

scan_overrides walks <root> (a data/overrides directory), finds every file that mentions a pilot CIK (path segment or
content: JSON strings and "cik" values, never other JSON numbers; non-JSON text line by line) and classifies it by the
table. It FAILS CLOSED: a mentioning file in a family without a class, or in a family that must not mention a pilot
filer, raises FamilyError (7.1: "a family added later without a class fails"). Process-artifact files above
MAX_SCAN_BYTES are matched on their path only (position_id_registry/registry.csv is ~112 MB); any other family above
the cap raises. Paths with an underscore-prefixed segment after the family, or a `.proposed.` file name, are
`not_loaded` (production skips them: pipeline/rule_admission.admitted, agent_promoted.load_promoted_rules).
Read-only; files are read as production reads them (utf-8-sig).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from scripts.profile_pilot.translate import value_sha256

REPO_PREFIX = "data/overrides/"
CLASSES = ("knowledge", "executable", "process_artifact", "not_applicable")
ACTIONS = ("entry", "correction", "wrapper_block", "excluded", "not_loaded", "foreign_mention")
SHARED_FILES = ("bdc_aggregate_row_overrides.json", "bdc_xbrl_oracle_exceptions.json")
MAX_SCAN_BYTES = 20_000_000
NOT_LOADED_REASON = ("production loaders skip underscore-prefixed or .proposed. paths "
                     "(pipeline/rule_admission.admitted)")
_NA = ("no pilot filer present (spec 7.1); classified when a filer that uses it enters the cohort")
FAMILY_CLASSES = {
    "rate_convention": dict(cls="knowledge", action="entry", reason="source of the meaning.interest_rate entry"),
    "identifier_rate_grammars": dict(cls="knowledge", action="entry",
                                     reason="source of the identifier_format.dialect entry"),
    "identifier_anchors": dict(cls="knowledge", action="entry",
                               reason="source of the identifier_format.anchors entry (same axis as grammars)"),
    "bdc_aggregate_row_overrides.json": dict(cls="knowledge", action="correction",
                                             reason="point-dated subtotal exclusions -> one-off corrections (P5)"),
    "bdc_xbrl_oracle_exceptions.json": dict(cls="knowledge", action="correction",
                                            reason="point-dated reconciliation-scope exceptions -> one-off corrections (P5)"),
    "agent_b2_corrections": dict(cls="knowledge", action="correction", reason="spec 4.2 corrections"),
    "identifier_spread_corrections.json": dict(cls="knowledge", action="must_be_absent",
                                               reason="gated off 2026-09-29 (e379e8a); retired per spec section 7"),
    "bdc_xbrl_wrappers": dict(cls="executable", action="wrapper_block", reason="wrapper section block (D-consolidate)"),
    "agent_investigate_rules": dict(cls="executable", action="wrapper_block",
                                    reason="second wrapper block (spec 7.1; P6)"),
    "agent_anchor": dict(cls="process_artifact", action="excluded",
                         reason="fleet output, regenerated per pass, not knowledge (spec 7.1)"),
    "wrapper_cohorts": dict(cls="process_artifact", action="excluded",
                            reason="cohort membership manifest, not per-filer semantics (spec 7.1)"),
    "position_id_registry": dict(cls="process_artifact", action="excluded",
                                 reason="opt-in matching state, read only by the row-continuity detector (spec 7.1)"),
    "enforcement_registry": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
    "bdc_xbrl_html_section_bridges": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
    "fund_highlights_wrappers": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
    "row_corrections.csv": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
    "entity_overrides.json": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
}
FILE_CLASSES = {
    "bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json": dict(
        cls="process_artifact", action="excluded",
        reason="SP3 classification (not in spec 7.1): unlisted-BDC reference listing for frontend filtering "
               "(config.UNLISTED_BDC_REFERENCE_FILE), not per-filer semantics; owner to confirm"),
}
_DIGITS = re.compile(r"\d{6,10}")


class FamilyError(ValueError):
    """An override file mentions a pilot filer in a family the disposition table does not allow."""


def cik10(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text.zfill(10) if text.isdigit() and len(text) <= 10 else None


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def raw_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def family_of(relative: str) -> str:
    return relative.split("/", 1)[0]


def owner_cik(relative: str) -> str | None:
    parts = relative.split("/")
    if len(parts) == 1:
        return None
    for part in parts[1:-1] + [parts[-1].rsplit(".", 1)[0]]:
        if _DIGITS.fullmatch(part):
            return part.zfill(10)
    return None


def is_loaded(relative: str) -> bool:
    parts = relative.split("/")
    return not any(p.startswith("_") for p in parts[1:]) and ".proposed." not in parts[-1].lower()


def classify_path(relative: str) -> dict | None:
    if relative in FILE_CLASSES:
        return FILE_CLASSES[relative]
    family = family_of(relative)
    if family in FAMILY_CLASSES:
        return FAMILY_CLASSES[family]
    if family.startswith("_"):
        return dict(cls="process_artifact", action="not_loaded", reason="retired store (underscore-prefixed family)")
    return None


def _patterns(ciks) -> dict:
    return {c: re.compile(r"(?<![0-9])0*" + str(int(c)) + r"(?![0-9])") for c in ciks}


def _strings(value, key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, key)
    elif isinstance(value, str):
        yield value
    elif key == "cik" and isinstance(value, int) and not isinstance(value, bool):
        yield str(value)


def _content_mentions(path: Path, patterns: dict) -> set:
    found = set()
    if path.suffix.lower() == ".json":
        try:
            texts = _strings(read_json(path))
        except (ValueError, UnicodeDecodeError):
            texts = [path.read_text(encoding="utf-8-sig", errors="replace")]
        for text in texts:
            found |= {c for c, pat in patterns.items() if c not in found and pat.search(text)}
        return found
    with open(path, encoding="utf-8-sig", errors="replace") as stream:
        for line in stream:
            found |= {c for c, pat in patterns.items() if c not in found and pat.search(line)}
    return found


def scan_overrides(root: Path, ciks) -> list[dict]:
    root = Path(root)
    patterns = _patterns([cik10(c) for c in ciks])
    hits = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        spec = classify_path(rel)
        mentioned = {c for c, pat in patterns.items() if pat.search(rel)}
        if path.stat().st_size > MAX_SCAN_BYTES:
            if spec is None or spec["cls"] != "process_artifact":
                raise FamilyError("file above MAX_SCAN_BYTES outside a process-artifact family: " + rel)
        else:
            mentioned |= _content_mentions(path, patterns)
        if not mentioned:
            continue
        if spec is None:
            raise FamilyError("unclassified override family with pilot filer mentions: " + rel
                              + " (" + ", ".join(sorted(mentioned)) + ")")
        if spec["action"] == "must_be_absent":
            raise FamilyError(rel + " must not mention a pilot filer (" + spec["reason"] + "): "
                              + ", ".join(sorted(mentioned)))
        loaded = is_loaded(rel)
        hits.append(dict(path=rel, family=family_of(rel), cls=spec["cls"],
                         action=spec["action"] if loaded else "not_loaded", ciks=sorted(mentioned),
                         owner=owner_cik(rel), reason=spec["reason"] if loaded else NOT_LOADED_REASON))
    return hits


def collect_override_inputs(root: Path, cik: str, hits: list[dict]) -> dict:
    root, cik = Path(root), cik10(cik)
    files, shared, disposition = {}, {}, []
    for hit in hits:
        if cik not in hit["ciks"]:
            continue
        rel = hit["path"]
        record = dict(path=rel, family=hit["family"], cls=hit["cls"], action=hit["action"],
                      sha256=raw_sha256(root / rel), ordered_sha256=None, targets=[], reason=hit["reason"],
                      record_indexes=None)
        if hit["action"] in ("excluded", "not_loaded"):
            disposition.append(record)
            continue
        if hit["owner"] not in (None, cik):
            disposition.append(dict(record, action="foreign_mention",
                                    reason="file belongs to filer " + hit["owner"] + "; mention recorded, not converted"))
            continue
        content = read_json(root / rel)
        record["ordered_sha256"] = value_sha256(content)
        if rel in SHARED_FILES:
            records = content["overrides"] if isinstance(content, dict) else content
            items = [[i, r] for i, r in enumerate(records) if cik10(r.get("cik")) == cik]
            if not items:   # mentioned only inside another filer's record (e.g. an accession in evidence text)
                disposition.append(dict(record, action="foreign_mention",
                                        reason="mentioned outside any record whose cik is this filer"))
                continue
            shared[rel] = dict(sha256=record["sha256"], records=items)
            record["record_indexes"] = [i for i, _ in items]
        else:
            files.setdefault(hit["family"], []).append(dict(path=rel, sha256=record["sha256"], content=content))
        disposition.append(record)
    return dict(files=files, shared=shared, disposition=disposition)
```

- [ ] **Step 4: Run to pass** (`sp3p-verify-t4b`).
- [ ] **Step 5: Commit** `Add the spec 7.1 override-family disposition table and scanner`.

### Task 5: Inception converter part 1: wrapper blocks and corrections

**Files:**
- Create: `scripts/profile_pilot/profile_inception.py` (wrapper and corrections half)
- Test: `tests/test_profile_pilot_profile_inception.py` (new)

**Interfaces:**
- Consumes: `profile_families.cik10/REPO_PREFIX`, `translate.value_sha256`, `profile_document.CONVERTER_VERSION` (Tasks 3-4).
- Produces:

```python
SIGNOFF_TAGS = ("signoff-2025-12-31", "signoff-2026-03-31")
PRE_IMAGE_REASON: str
SHARED_MECHANISM = {"bdc_aggregate_row_overrides.json": ("aggregate_row", "aggregate_row_exclusion"),
                    "bdc_xbrl_oracle_exceptions.json": ("oracle_exception", "reconciliation_scope_exception")}
class InceptionError(ValueError)
def wrapper_block(cik, *, family, files, recorded_at, attested_under) -> dict     # schema $defs/block
    # family "bdc_xbrl_wrapper" (exactly one file; content = the wrapper, key order kept) or
    # "agent_investigate_rules" (content = {"files": {relative path: rule}}; expressibility per file)
def rule_expressibility(rule: dict) -> dict      # {"expressible_as": "one_off_correction" | None, "reason": str}
def correction_records(cik, *, b2_files, shared, recorded_at, run_id) -> list[dict]   # schema $defs/correction
def mark_recurrence(corrections: list[dict]) -> list[dict]
```

Correction ids: `<cik>:corr:b2:NNN` (B2 files in path order), `<cik>:corr:aggregate_row:NNN`, `<cik>:corr:oracle_exception:NNN` (records in file order). Kind: exactly one report date -> `one_off` (state `accepted`, basis `inherited_production`); >= 2 -> `multi_quarter`, none -> `undated` (both `candidate`, basis `not_one_off_at_inception`). B2 report dates = `scope.quarters` + `template.report_date` + `template.row_selector.report_date`. Recurrence: one-off corrections of one family, mechanism and signature (aggregate: `match_text`; oracle: `oracle_reason`; B2: `fix_class`) in >= 2 distinct report dates share `recurrence_group = <cik>:recur:<12 hex>` and `promotion = proposed_recurring_owner_tier`.

- [ ] **Step 1: Failing tests** (`tests/test_profile_pilot_profile_inception.py`):

```python
"""SP3 proper Tasks 5-6: inception converter (wrapper blocks, corrections, entries, stubs, build_document)."""
from __future__ import annotations

import copy

import pytest

from scripts.profile_pilot import profile_inception as pi
from tests.test_profile_pilot_profile_families import ARES, STELLUS, wrapper_v3

NOW = "2026-10-01T12:00:00Z"
RUN = "sp3p-profile-test"
SHA = "d" * 64


def f(path, content, sha=SHA):
    return dict(path=path, sha256=sha, content=content)


def test_wrapper_block_keeps_key_order_and_identity():
    w = wrapper_v3(ARES)
    block = pi.wrapper_block(ARES, family="bdc_xbrl_wrapper", files=[f("bdc_xbrl_wrappers/" + ARES + ".json", w)],
                             recorded_at=NOW, attested_under=["signoff-2026-03-31"])
    assert block["block_id"] == ARES + ":wrapper:bdc_xbrl_wrapper:v1"
    assert list(block["content"]["dispatch"]["prefix_rules"]) == ["Second Lien", "First Lien"]
    assert block["valid_from"] is None and block["valid_to"] is None and block["attested_under"] == ["signoff-2026-03-31"]
    assert block["source_files"][0]["ordered_sha256"] == block["content_sha256"]
    flipped = copy.deepcopy(w)
    flipped["dispatch"]["prefix_rules"] = {"First Lien": "debt", "Second Lien": "debt"}
    other = pi.wrapper_block(ARES, family="bdc_xbrl_wrapper", files=[f("x", flipped)], recorded_at=NOW, attested_under=[])
    assert other["content_sha256"] != block["content_sha256"]   # order is behaviour


def test_wrapper_block_refuses_two_files_or_a_foreign_cik():
    with pytest.raises(pi.InceptionError):
        pi.wrapper_block(ARES, family="bdc_xbrl_wrapper", files=[f("a", wrapper_v3(ARES)), f("b", wrapper_v3(ARES))],
                         recorded_at=NOW, attested_under=[])
    with pytest.raises(pi.InceptionError):
        pi.wrapper_block(ARES, family="bdc_xbrl_wrapper", files=[f("a", wrapper_v3(STELLUS))], recorded_at=NOW,
                         attested_under=[])


def test_rules_block_and_expressibility():
    excl = {"cik": "1287750", "rule_id": "x", "rule_type": "row_exclusion", "scope": {"quarters": ["2025-09-30"]},
            "predicate_sql": "report_date = '2025-09-30' AND row_id IN ('ROW-1', 'ROW-2')"}
    add = {"cik": "1287750", "rule_id": "y", "rule_type": "row_add", "scope": {"quarters": ["2023-06-30"]}}
    block = pi.wrapper_block(ARES, family="agent_investigate_rules",
                             files=[f("agent_investigate_rules/1287750/y.json", add),
                                    f("agent_investigate_rules/1287750/x.json", excl)],
                             recorded_at=NOW, attested_under=[])
    assert list(block["content"]["files"]) == ["agent_investigate_rules/1287750/x.json",
                                               "agent_investigate_rules/1287750/y.json"]
    exp = block["expressibility"]
    assert exp["agent_investigate_rules/1287750/x.json"]["expressible_as"] == "one_off_correction"
    assert exp["agent_investigate_rules/1287750/y.json"]["expressible_as"] is None


def b2(fix_class, **extra):
    leaf = {"cik": ARES, "mechanism": "extraction_gap", "fix_class": fix_class, "template": {},
            "confidence": 0.9}
    leaf.update(extra)
    return f("agent_b2_corrections/" + ARES + "/" + fix_class + ".json", leaf)


def test_b2_corrections_kinds_and_targets():
    files = [b2("all_pik_normalization", scope={"quarters": ["2025-12-31"]},
                template={"row_selector": {"row_id": "ROW-62c1"}, "cash_rate": 0.0, "pik_rate": 14.0}),
             b2("column_remap", scope={"quarters": ["2025-12-31"]}, template={"from_field": "pik_rate", "to_field": "interest_rate"}),
             b2("comparative_period_filter", template={"report_date": "2025-12-31"}),
             b2("unit_rescale", scope={"quarters": ["2025-09-30", "2025-12-31"]}),
             b2("zero_fill")]
    out = {c["fix_class"]: c for c in pi.correction_records(ARES, b2_files=files, shared={}, recorded_at=NOW,
                                                            run_id=RUN)}
    pik = out["all_pik_normalization"]
    assert (pik["kind"], pik["report_date"], pik["valid_from"], pik["valid_to"]) == ("one_off",) + ("2025-12-31",) * 3
    assert pik["row_keyed"] is True and pik["target"] == {"row_id": "ROW-62c1"} and pik["state"] == "accepted"
    assert pik["pre_image"]["status"] == "unchecked" and pik["confidence"] == 0.9
    assert out["column_remap"]["target"] == {"report_dates": ["2025-12-31"]} and out["column_remap"]["row_keyed"] is False
    assert out["comparative_period_filter"]["report_date"] == "2025-12-31"
    assert (out["unit_rescale"]["kind"], out["unit_rescale"]["state"]) == ("multi_quarter", "candidate")
    assert (out["zero_fill"]["kind"], out["zero_fill"]["report_date"]) == ("undated", None)
    assert out["all_pik_normalization"]["value"] == files[0]["content"]


def test_b2_leaf_of_another_filer_is_refused():
    leaf = b2("column_remap", scope={"quarters": ["2025-12-31"]})
    leaf["content"]["cik"] = STELLUS
    with pytest.raises(pi.InceptionError):
        pi.correction_records(ARES, b2_files=[leaf], shared={}, recorded_at=NOW, run_id=RUN)


def test_shared_records_become_one_offs_with_recurrence():
    ivy = [[1 + i, {"cik": ARES, "report_date": d, "accession_number": "acc-" + d, "match_text": "Ivy Hill",
                    "match_mode": "exact", "action": "exclude"}]
           for i, d in enumerate(("2025-06-30", "2025-09-30", "2025-12-31"))]
    single = [[9, {"cik": ARES, "report_date": "2023-03-31", "accession_number": "acc", "match_text": "Other",
                   "match_mode": "exact", "action": "exclude"}]]
    shared = {"bdc_aggregate_row_overrides.json": {"sha256": SHA, "records": ivy + single}}
    out = pi.correction_records(ARES, b2_files=[], shared=shared, recorded_at=NOW, run_id=RUN)
    assert [c["correction_id"] for c in out] == [ARES + ":corr:aggregate_row:%03d" % n for n in (1, 2, 3, 4)]
    groups = {c["recurrence_group"] for c in out[:3]}
    assert len(groups) == 1 and None not in groups
    assert all(c["promotion"] == "proposed_recurring_owner_tier" for c in out[:3])
    assert out[3]["recurrence_group"] is None and out[3]["promotion"] is None
    assert out[0]["source"] == {"path": "bdc_aggregate_row_overrides.json", "sha256": SHA, "record_index": 1}
    assert out[0]["mechanism"] == "aggregate_row_exclusion" and out[0]["target"]["match_text"] == "Ivy Hill"
```

- [ ] **Step 2: Run to fail** (`sp3p-verify-t5a`).

- [ ] **Step 3: Implement** the first half of `scripts/profile_pilot/profile_inception.py`:

```python
"""SP3 proper: inception converter -- existing override files and the Q4-2025 census -> profile document v1.

Pure (no file access); the CLI (profile_document_run) reads the files and passes their parsed content. Spec 4
inception: the override file's value becomes the entry value, its citations the evidence, its content hash the
pre-image; a filer with no file on an axis gets a census-derived entry or an insufficient-evidence stub.
Dispositions (spec 7.1, plan decisions P1-P11): knowledge files -> entries (rate_convention, grammars, anchors) or
one-off corrections (B2, aggregate rows, oracle exceptions); executable files -> wrapper blocks (wrapper,
agent_investigate_rules). Key order inside override content is preserved everywhere (prefix_rules is first-match).
"""
from __future__ import annotations

import copy
import re

from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot.profile_families import REPO_PREFIX, cik10
from scripts.profile_pilot.translate import value_sha256

SIGNOFF_TAGS = ("signoff-2025-12-31", "signoff-2026-03-31")
PRE_IMAGE_REASON = ("criterion 5 pre-image check (row_id present, pre-image unchanged) runs on the rebuilt quarter "
                    "in sub-project 6")
SHARED_MECHANISM = {"bdc_aggregate_row_overrides.json": ("aggregate_row", "aggregate_row_exclusion"),
                    "bdc_xbrl_oracle_exceptions.json": ("oracle_exception", "reconciliation_scope_exception")}
_ROW_ID_SQL = re.compile(r"\brow_id\s+IN\s*\(", re.IGNORECASE)


class InceptionError(ValueError):
    """The override inputs cannot be converted without guessing."""


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def rule_expressibility(rule: dict) -> dict:
    quarters = (rule.get("scope") or {}).get("quarters") or []
    if (rule.get("rule_type") == "row_exclusion" and _ROW_ID_SQL.search(rule.get("predicate_sql") or "")
            and len(quarters) == 1):
        return dict(expressible_as="one_off_correction",
                    reason="row_id-keyed exclusion scoped to one quarter (spec 4.2); conversion is sub-project 6")
    return dict(expressible_as=None, reason="executable rule_type " + repr(rule.get("rule_type"))
                + " stays in the wrapper section (spec 7.1)")


def wrapper_block(cik, *, family, files, recorded_at, attested_under) -> dict:
    files = sorted(files, key=lambda x: x["path"])
    if family == "bdc_xbrl_wrapper":
        if len(files) != 1:
            raise InceptionError("exactly one wrapper file per filer: " + repr([x["path"] for x in files]))
        content = copy.deepcopy(files[0]["content"])
        if cik10(content.get("cik")) != cik:
            raise InceptionError("wrapper cik " + repr(content.get("cik")) + " is not " + cik)
        expressibility = None
    elif family == "agent_investigate_rules":
        content = {"files": {x["path"]: copy.deepcopy(x["content"]) for x in files}}
        expressibility = {x["path"]: rule_expressibility(x["content"]) for x in files}
    else:
        raise InceptionError("unknown block family " + repr(family))
    sources = [dict(path=x["path"], sha256=x["sha256"], ordered_sha256=value_sha256(x["content"])) for x in files]
    evidence = [dict(kind="override_file", path=REPO_PREFIX + s["path"], sha256=s["sha256"],
                     ordered_sha256=s["ordered_sha256"]) for s in sources]
    evidence.append(dict(kind="attestation", tags=sorted(attested_under),
                         rule="tag lists the sign-off tags whose blob parses order-identical to the file read"))
    return dict(block_id=cik + ":wrapper:" + family + ":v1", family=family, version=1, content=content,
                content_sha256=value_sha256(content), source_files=sources, valid_from=None, valid_to=None,
                recorded_at=recorded_at, recorded_until=None, supersedes=None, supersession_kind=None,
                attested_under=sorted(attested_under), evidence=evidence, expressibility=expressibility)


def _b2_dates(leaf: dict) -> list:
    template = leaf.get("template") or {}
    selector = template.get("row_selector") or {}
    dates = set((leaf.get("scope") or {}).get("quarters") or [])
    for value in (template.get("report_date"), selector.get("report_date")):
        if value:
            dates.add(value)
    return sorted(dates)


def _correction(cik, n, tag, *, family, mechanism, fix_class, dates, target, row_keyed, value, source,
                recorded_at, run_id, author) -> dict:
    one_off = len(dates) == 1
    kind = "one_off" if one_off else ("multi_quarter" if dates else "undated")
    day = dates[0] if one_off else None
    return dict(correction_id="%s:corr:%s:%03d" % (cik, tag, n), kind=kind, family=family, mechanism=mechanism,
                fix_class=fix_class, report_date=day, valid_from=day, valid_to=day, report_dates=list(dates),
                target=target, row_keyed=row_keyed, value=copy.deepcopy(value), source=source,
                pre_image=dict(status="unchecked", reason=PRE_IMAGE_REASON), recurrence_group=None, promotion=None,
                state="accepted" if one_off else "candidate",
                admission_basis="inherited_production" if one_off else "not_one_off_at_inception",
                confidence=_number(value.get("confidence")),
                provenance=dict(who=pd.CONVERTER_VERSION, source_author=str(value.get("created_by") or author),
                                when=recorded_at, run_id=run_id, source=REPO_PREFIX + source["path"]),
                recorded_at=recorded_at, recorded_until=None, supersedes=None)


def correction_records(cik, *, b2_files, shared, recorded_at, run_id) -> list[dict]:
    out = []
    for n, item in enumerate(sorted(b2_files, key=lambda x: x["path"]), 1):
        leaf = item["content"]
        if cik10(leaf.get("cik")) != cik:
            raise InceptionError("B2 leaf cik differs from its filer: " + item["path"])
        selector = (leaf.get("template") or {}).get("row_selector")
        dates = _b2_dates(leaf)
        out.append(_correction(cik, n, "b2", family="agent_b2_corrections", mechanism=leaf.get("mechanism"),
                               fix_class=leaf.get("fix_class"), dates=dates,
                               target=dict(selector) if selector else {"report_dates": dates},
                               row_keyed=bool(selector and selector.get("row_id")), value=leaf,
                               source=dict(path=item["path"], sha256=item["sha256"], record_index=None),
                               recorded_at=recorded_at, run_id=run_id, author="agent"))
    for name in sorted(shared):
        tag, mechanism = SHARED_MECHANISM[name]
        for n, (index, record) in enumerate(shared[name]["records"], 1):
            if cik10(record.get("cik")) != cik:
                raise InceptionError(name + " record " + str(index) + " belongs to another filer")
            if tag == "aggregate_row":
                target = {k: record.get(k) for k in ("report_date", "accession_number", "match_text", "match_mode")}
                fix = record.get("action")
            else:
                target = {"report_date": record.get("report_date"), "oracle_reason": record.get("oracle_reason")}
                fix = record.get("oracle_reason")
            day = record.get("report_date")
            out.append(_correction(cik, n, tag, family=name, mechanism=mechanism, fix_class=fix,
                                   dates=[day] if day else [], target=target, row_keyed=False, value=record,
                                   source=dict(path=name, sha256=shared[name]["sha256"], record_index=index),
                                   recorded_at=recorded_at, run_id=run_id, author="agent"))
    return mark_recurrence(out)


def _signature(c: dict) -> str:
    if c["family"] == "bdc_aggregate_row_overrides.json":
        return str(c["target"].get("match_text"))
    if c["family"] == "bdc_xbrl_oracle_exceptions.json":
        return str(c["target"].get("oracle_reason"))
    return str(c["fix_class"])


def mark_recurrence(corrections: list[dict]) -> list[dict]:
    groups: dict = {}
    for c in corrections:
        if c["kind"] == "one_off":
            groups.setdefault((c["family"], c["mechanism"], _signature(c)), []).append(c)
    for key, members in groups.items():
        if len({m["report_date"] for m in members}) >= 2:
            gid = members[0]["correction_id"].split(":corr:")[0] + ":recur:" + value_sha256(list(key))[:12]
            for m in members:
                m.update(recurrence_group=gid, promotion="proposed_recurring_owner_tier")
    return corrections
```

- [ ] **Step 4: Run to pass** (`sp3p-verify-t5b`).
- [ ] **Step 5: Commit** `Convert wrappers, investigate rules and corrections into profile blocks and corrections`.

### Task 6: Inception converter part 2: entries, admissions, stubs, `build_document`

**Files:**
- Modify: `scripts/profile_pilot/profile.py` (add `INCEPTION_ERA`, `DERIVE_ERAS`; `derive_profile` accepts `era="inception"`; `ERAS` unchanged so `profile_run` still derives two eras)
- Modify: `scripts/profile_pilot/schemas/filer_profile_document_v0.schema.json` (`era` enum `["q1", "same_era", "inception"]`)
- Modify: `scripts/profile_pilot/profile_inception.py` (second half)
- Test: `tests/test_profile_pilot_profile_inception.py` (append; exports `census`, `inception_inputs`, `Q4`, `Q1`)

**Interfaces:**
- Consumes: `profile.derive_profile` (Stage B census derivation, no wrapper access), `envelope.make_assertion` (Task 1), `profile_document.admission/stub/validate_document/valid_at/GRID_KEYS` (Task 3), `wrapper_block/correction_records` (Task 5), `translate._get/pointer`.
- Produces:

```python
INHERITED_FAMILIES = {"rate_convention": ("meaning.interest_rate", "agent"),
                      "identifier_rate_grammars": ("identifier_format.dialect", "agent"),
                      "identifier_anchors": ("identifier_format.anchors", "agent")}
PREDICATE_CODE_PATH = "scripts/profile_pilot/census_published.py"
REPORTING_ENTITY_POINTER = ("source_encodings", "reporting_entity_suffixes")
CENSUS_KEYS: frozenset[str]          # grid keys the Stage B census can derive
CLOSING_EVIDENCE: dict[str, str]     # key section -> evidence that would close a no_source stub
def file_evidence(rel, sha, content, *, value_is_file=True, pointer=None) -> list[dict]
def census_entries(census: dict | None, *, recorded_at) -> tuple[list, list]          # (events, census packet stubs)
def confirmations(q4_entries: list, q1_census: dict | None, *, recorded_at) -> dict  # entry_id -> (bool, reason)
def grid_stubs(cik, entries, admissions, census_stubs, *, report_date, census_unavailable) -> list[dict]
def build_document(cik: str, *, inputs: dict, recorded_at: str, run_id: str, git_head: str) -> dict
```

`inputs` (built by the CLI in Task 9 from `profile_families.collect_override_inputs` plus):
`files`, `shared`, `disposition` (Task 4 shapes); `attested_under: {relative path: [tags]}`;
`census_q4` / `census_q1`: `{"doc": <census result>, "source": {cik, report_date, role, census_relative, census_sha256, fingerprint, accession_number, form_type}}` or None;
`census_q4_unavailable`: `{"census_run_id", "reason", "detail"}` or None;
`detection: {kind: {"verdict", "replay_run_id"}}`; `predicate: {"version", "code_sha256"}`;
`code_mirror: [str]` (`census_published.REPORTING_ENTITIES.get(cik, ())`); `overrides_root: str`; `replay_run_id: str`.

Ordering inside a document (deterministic): census events, then inherited families in sorted family order, then `partition_structure.published_basis`, then `partition_structure.reporting_entities`; blocks wrapper then rules; corrections B2 then shared files in name order.

- [ ] **Step 1: Failing tests** (append to `tests/test_profile_pilot_profile_inception.py`):

```python
from scripts.profile_pilot import profile
from scripts.profile_pilot import profile_document as pd
from tests.test_profile_pilot_profile import mini_doc, single_dialect

Q4, Q1 = "2025-12-31", "2026-03-31"


def census(date, identifiers=None, delim="|"):
    doc = mini_doc(partition=[single_dialect(delim)], report_date=date, identifiers=identifiers)
    source = dict(cik=STELLUS, report_date=date, role="all:" + date,
                  census_relative="census/" + STELLUS + "/" + date + ".json", census_sha256="0" * 64,
                  fingerprint="f" * 64, accession_number="0000000000-23-000001", form_type="10-Q")
    return dict(doc=doc, source=source)


def inception_inputs(*, q4=True, q1=True, wrapper=None, extra_files=None, shared=None):
    w = wrapper or wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ["Emerald JV LP"]})
    files = {"bdc_xbrl_wrappers": [f("bdc_xbrl_wrappers/" + STELLUS + ".json", w)],
             "rate_convention": [f("rate_convention/" + STELLUS + ".json",
                                   {"cik": STELLUS, "convention": "all_in", "target_quarter": Q1, "confidence": 0.8,
                                    "citations": [{"kind": "header", "quote": "Interest Rate (2)"}]})]}
    files.update(extra_files or {})
    action = {"bdc_xbrl_wrappers": "wrapper_block", "agent_investigate_rules": "wrapper_block",
              "agent_b2_corrections": "correction"}
    disposition = [dict(path=x["path"], family=fam,
                        cls="executable" if action.get(fam) == "wrapper_block" else "knowledge",
                        action=action.get(fam, "entry"), sha256=x["sha256"], ordered_sha256=None, targets=[],
                        reason=None, record_indexes=None)
                   for fam, items in files.items() for x in items]
    for name, s in (shared or {}).items():
        disposition.append(dict(path=name, family=name, cls="knowledge", action="correction", sha256=s["sha256"],
                                ordered_sha256=None, targets=[], reason=None,
                                record_indexes=[i for i, _ in s["records"]]))
    return dict(files=files, shared=shared or {}, disposition=disposition,
                attested_under={"bdc_xbrl_wrappers/" + STELLUS + ".json": ["signoff-2026-03-31"]},
                census_q4=census(Q4) if q4 else None,
                census_q4_unavailable=None if q4 else dict(census_run_id="stageb2-sp1census-20260930t2235z",
                                                           reason="unavailable",
                                                           detail="ambiguous_same_quarter_candidates"),
                census_q1=census(Q1) if q1 else None,
                detection={"fill_rate": dict(verdict="NO_POSITIVES", replay_run_id="sp1-replay-x"),
                           "source_concept_set": dict(verdict="PASS", replay_run_id="sp1-replay-x")},
                predicate=dict(version="census-published.v2", code_sha256="e" * 64),
                code_mirror=["Emerald JV LP"], overrides_root="tmp", replay_run_id="sp1-replay-x")


def build(**kw):
    return pi.build_document(STELLUS, inputs=inception_inputs(**kw), recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_derive_profile_accepts_the_inception_era_without_changing_eras():
    assert profile.ERAS == ("q1", "same_era") and profile.INCEPTION_ERA == "inception"
    c = census(Q4)
    out = profile.derive_profile(c["doc"], source=c["source"], era=profile.INCEPTION_ERA, recorded_at=NOW, anchors=None)
    profile.validate_document(out)
    assert out["era"] == "inception"


def test_build_document_full():
    doc = build()
    pd.validate_document(doc)
    by_key = {e["key"]: e for e in doc["entries"]}
    delim = by_key["identifier_format.delimiter"]
    assert delim["value"] == " | "
    assert doc["admissions"][delim["entry_id"]]["state"] == "accepted"
    assert doc["admissions"][delim["entry_id"]]["basis"] == "census_confirmed_next_quarter"
    conv = by_key["meaning.interest_rate"]
    assert conv["valid_from"] is None and conv["provenance"] == "inherited" and conv["author"] == "agent"
    assert conv["support"]["kind"] == "inherited_file" and conv["value"]["convention"] == "all_in"
    assert doc["admissions"][conv["entry_id"]]["confidence"] == 0.8
    assert {"kind": "source_date", "field": "target_quarter", "value": Q1} in conv["evidence"]
    assert by_key["partition_structure.published_basis"]["value"] == {"predicate": "census-published.v2"}
    ents = by_key["partition_structure.reporting_entities"]
    assert ents["value"] == ["Emerald JV LP"]
    assert doc["partition_predicate"]["reporting_entities_entry_id"] == ents["entry_id"]
    assert doc["partition_predicate"]["code_mirror"]["value"] == ["Emerald JV LP"]
    [block] = doc["wrapper_section"]["blocks"]
    assert block["attested_under"] == ["signoff-2026-03-31"]
    assert doc["detection_claims"]["fill_rate"]["claim"] == "detection_not_claimed"
    assert doc["detection_claims"]["source_concept_set"]["claim"] == "claimed"
    targets = {d["path"]: d["targets"] for d in doc["disposition"]}
    assert targets["bdc_xbrl_wrappers/" + STELLUS + ".json"] == [ents["entry_id"], block["block_id"]]
    assert targets["rate_convention/" + STELLUS + ".json"] == [conv["entry_id"]]
    for key, cell in pd.coverage(doc, Q4).items():
        assert cell["accepted_entry_ids"] or cell["stub"], key
    assert pd.resolve(doc, "scale_unit.fair_value", Q4)["stub"]["cause"] == "no_source"
    assert all(e["evidence"] for e in doc["entries"])


def test_unconfirmed_census_entry_is_a_candidate_with_a_stub():
    inputs = inception_inputs()
    inputs["census_q1"] = census(Q1, identifiers=["Borrower %d LLC ; Term Loan" % i for i in range(12)], delim=";")
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    delim = next(e for e in doc["entries"] if e["key"] == "identifier_format.delimiter")
    assert doc["admissions"][delim["entry_id"]]["state"] == "candidate"
    assert doc["admissions"][delim["entry_id"]]["witness"] == {"next_quarter": "q1_value_differs"}
    out = pd.resolve(doc, "identifier_format.delimiter", Q4)
    assert out["status"] == "stub" and out["stub"]["cause"] == "candidate_pending_confirmation"
    assert out["stub"]["entry_id"] == delim["entry_id"]


def test_census_unavailable_gives_census_unavailable_stubs():
    doc = build(q4=False, q1=False)
    assert not any(e["key"].startswith("column_contract.") for e in doc["entries"])
    stub = pd.resolve(doc, "column_contract.fair_value", Q4)["stub"]
    assert stub["cause"] == "census_unavailable" and "ambiguous_same_quarter_candidates" in stub["closing_evidence"]
    assert pd.resolve(doc, "income_proofs.duration", Q4)["stub"]["cause"] == "no_source"
    assert doc["ledger"][0]["detail"]["census_q4"] is None


def test_two_files_in_one_knowledge_family_are_refused():
    inputs = inception_inputs()
    inputs["files"]["rate_convention"].append(f("rate_convention/other.json", {"cik": STELLUS, "convention": "cash"}))
    with pytest.raises(pi.InceptionError):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_a_converted_file_that_produces_nothing_is_refused():
    inputs = inception_inputs()
    inputs["disposition"].append(dict(path="identifier_anchors/" + STELLUS + ".json", family="identifier_anchors",
                                      cls="knowledge", action="entry", sha256=SHA, ordered_sha256=None, targets=[],
                                      reason=None, record_indexes=None))
    with pytest.raises(pi.InceptionError, match="produced nothing"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_shared_records_land_as_recurring_one_offs():
    rows = [[0, {"cik": STELLUS, "report_date": "2025-09-30", "oracle_reason": "rate_outliers_detected", "confidence": 0.9}],
            [1, {"cik": STELLUS, "report_date": "2025-12-31", "oracle_reason": "rate_outliers_detected", "confidence": 0.9}]]
    doc = build(shared={"bdc_xbrl_oracle_exceptions.json": {"sha256": SHA, "records": rows}})
    assert [c["kind"] for c in doc["corrections"]] == ["one_off", "one_off"]
    assert doc["corrections"][0]["recurrence_group"] == doc["corrections"][1]["recurrence_group"]
    assert doc["corrections"][0]["recurrence_group"] is not None
```

- [ ] **Step 2: Run to fail** (`sp3p-verify-t6a`): `AttributeError: module ... has no attribute 'INCEPTION_ERA'` / `build_document`.

- [ ] **Step 3: Implement.** In `profile.py`, below `ERAS`:

```python
INCEPTION_ERA = "inception"           # SP3 proper: the Q4-2025 inception derivation; not a Stage B era
DERIVE_ERAS = ERAS + (INCEPTION_ERA,)
```

and in `derive_profile` replace `if era not in ERAS:` with `if era not in DERIVE_ERAS:`. In the v0 document schema set `"era": {"enum": ["q1", "same_era", "inception"]}`.

Append to `profile_inception.py` (move the two import lines into the module's import block):

```python
from scripts.profile_pilot import envelope, profile
from scripts.profile_pilot.translate import _get, pointer

INHERITED_FAMILIES = {"rate_convention": ("meaning.interest_rate", "agent"),
                      "identifier_rate_grammars": ("identifier_format.dialect", "agent"),
                      "identifier_anchors": ("identifier_format.anchors", "agent")}
PREDICATE_CODE_PATH = "scripts/profile_pilot/census_published.py"
REPORTING_ENTITY_POINTER = ("source_encodings", "reporting_entity_suffixes")
NO_CONTRACT = "none_available: no contract kind for this axis has reported (sub-project 2)"
ADOPTION_EVIDENCE = (
    dict(kind="adoption_record", changelog="docs/agent_changelog.md",
         heading="2026-10-01 -- SP3 Task 0b: census published-basis predicate v2 (hierarchical rollups) adopted",
         commits=["2132a31", "8418644", "b2454c9", "c7a627f"],
         rule="anchor-aware adoption rule (controller rulings 3-4): 101 measured fund-quarters, 0 violations, "
              "0 worsenings (IN-SAMPLE)",
         table="scratch/2026-09-30_base_build/diag_predicate_v2_table.csv"),
    dict(kind="owner_ruling", changelog="docs/agent_changelog.md",
         heading="2026-09-30 -- Published basis excludes underlying-schedule rows (owner ruling)"))
CENSUS_KEYS = frozenset(k for k in pd.GRID_KEYS
                        if k.split(".", 1)[0] in ("column_contract", "subtotals_and_headings", "fund_level_concepts")
                        ) | {"identifier_format.delimiter"}
CLOSING_EVIDENCE = {
    "column_contract": "a complete-collection census of this report date deriving the field's carrying concepts",
    "scale_unit": "the declared unit on the census unit channel, or a reconciling independent total "
                  "(spec 6 scale witness)",
    "meaning": "an adjudicated rate-convention verdict with an income-reconciliation witness (spec 6; D-convention)",
    "identifier_format": "a resolved partition-detector outcome on the census, or an Agent A grammar/anchor file",
    "subtotals_and_headings": "a resolved subtotal-detector outcome on the census",
    "fund_level_concepts": "single DEI or fund-total facts at the document period end in the census",
    "partition_structure": "a wrapper source_encodings list or a LegalEntityAxis observation naming the filer's "
                           "reporting entities",
    "income_proofs": "the income-proof step entries of the redesigned income-yield kind (spec 5), each with its "
                     "contract",
}


def file_evidence(rel, sha, content, *, value_is_file=True, pointer=None) -> list:
    item = dict(kind="override_file", path=REPO_PREFIX + rel, sha256=sha, ordered_sha256=value_sha256(content),
                value_is_file=value_is_file)
    if pointer is not None:
        item["pointer"] = pointer
    out = [item]
    if isinstance(content, dict):
        for k in ("citations", "evidence_citations", "evidence"):
            v = content.get(k)
            if isinstance(v, list) and v:
                out.append(dict(kind="source_citations", field=k, items=copy.deepcopy(v)))
        for k in ("target_quarter", "first_seen_quarter", "updated_at"):
            if content.get(k):
                out.append(dict(kind="source_date", field=k, value=content[k]))
    return out


def _assert_inherited(events, cik, key, value, *, support_path, sha, evidence, author, recorded_at):
    before = {e["entry_id"] for e in envelope.materialize_entries(events)}
    events = envelope.make_assertion(
        events, cik=cik, key=key, value=copy.deepcopy(value), valid_from=None, recorded_at=recorded_at,
        support=dict(kind="inherited_file", path=support_path, sha256=sha), evidence=evidence,
        provenance="inherited", inherited_from=support_path + "@" + sha[:12], author=author, status="promoted")
    new = [e["entry_id"] for e in envelope.materialize_entries(events) if e["entry_id"] not in before]
    if len(new) != 1:
        raise InceptionError("expected one new entry for " + key + ", got " + repr(new))
    return events, new[0]


def census_entries(census, *, recorded_at):
    if census is None:
        return [], []
    derived = profile.derive_profile(census["doc"], source=census["source"], era=profile.INCEPTION_ERA,
                                     recorded_at=recorded_at, anchors=None)
    return list(derived["events"]), list(derived["packet_stubs"])


def confirmations(q4_entries, q1_census, *, recorded_at) -> dict:
    if q1_census is None:
        return {e["entry_id"]: (False, "q1_census_unavailable") for e in q4_entries}
    q1 = profile.derive_profile(q1_census["doc"], source=q1_census["source"], era=profile.INCEPTION_ERA,
                                recorded_at=recorded_at, anchors=None)
    by_key: dict = {}
    for e in q1["entries"]:
        by_key.setdefault(e["key"], []).append(e)
    out = {}
    for e in q4_entries:
        others = by_key.get(e["key"], [])
        if len(others) != 1:
            out[e["entry_id"]] = (False, "q1_no_entry" if not others else "q1_ambiguous")
        elif (value_sha256(others[0]["value"]) == value_sha256(e["value"])
              and others[0]["applies_to"] == e["applies_to"]):
            out[e["entry_id"]] = (True, "q1_value_equal")
        else:
            out[e["entry_id"]] = (False, "q1_value_differs")
    return out


def grid_stubs(cik, entries, admissions, census_stubs, *, report_date, census_unavailable) -> list:
    live = [e for e in entries if e["recorded_until"] is None and pd.valid_at(e, report_date)]
    stubs = []
    for key in pd.GRID_KEYS:
        mine = [e for e in live if e["key"] == key]
        if any(admissions[e["entry_id"]]["state"] == "accepted" for e in mine):
            continue
        section = key.split(".", 1)[0]
        if mine:
            first = mine[0]
            reason = admissions[first["entry_id"]]["witness"].get("next_quarter", "not confirmed")
            stubs.append(pd.stub(cik, key, "candidate_pending_confirmation",
                                 "next-quarter confirmation of " + first["entry_id"] + " (inception: " + reason
                                 + "); admission loop, sub-project 5", entry_id=first["entry_id"],
                                 detail=dict(next_quarter=reason)))
            continue
        bearing = [s for s in census_stubs if key in (s.get("bears_on") or [])]
        if bearing:
            first = bearing[0]
            question = first.get("question") or ("census detector " + str(first.get("detector")) + " outcome "
                                                 + str(first.get("cause")))
            stubs.append(pd.stub(cik, key, "census_stub", question,
                                 detail=dict(census_stub_ids=[s["stub_id"] for s in bearing],
                                             cause=first.get("cause"), finding=first.get("finding"))))
            continue
        if census_unavailable and key in CENSUS_KEYS:
            stubs.append(pd.stub(cik, key, "census_unavailable",
                                 "an authoritative " + report_date + " census for " + cik + " ("
                                 + census_unavailable["census_run_id"] + " excluded it: "
                                 + str(census_unavailable.get("detail") or census_unavailable.get("reason")) + ")",
                                 detail=dict(census_unavailable)))
            continue
        stubs.append(pd.stub(cik, key, "no_source", CLOSING_EVIDENCE[section]))
    return stubs


def build_document(cik: str, *, inputs: dict, recorded_at: str, run_id: str, git_head: str) -> dict:
    cik = cik10(cik)
    files = inputs["files"]
    events, census_stubs = census_entries(inputs.get("census_q4"), recorded_at=recorded_at)
    admissions, targets = {}, {}
    q4_entries = envelope.materialize_entries(events)
    confirmed = confirmations(q4_entries, inputs.get("census_q1"), recorded_at=recorded_at)
    for e in q4_entries:
        ok, reason = confirmed[e["entry_id"]]
        admissions[e["entry_id"]] = pd.admission(
            "accepted" if ok else "candidate", "census_confirmed_next_quarter" if ok else "census_unconfirmed",
            source_kind="census", mechanism="census-derived (" + profile.PROFILE_VERSION + ")", confidence=None,
            source_author="census", recorded_at=recorded_at, run_id=run_id,
            source=inputs["census_q4"]["source"]["census_relative"], witness={"next_quarter": reason},
            inception_evaluation="next_quarter_census_equality")
    for family in sorted(INHERITED_FAMILIES):
        found = files.get(family) or []
        if not found:
            continue
        if len(found) != 1:
            raise InceptionError("more than one " + family + " file for " + cik + ": "
                                 + repr([x["path"] for x in found]))
        key, author = INHERITED_FAMILIES[family]
        item, content = found[0], found[0]["content"]
        meta = content if isinstance(content, dict) else {}
        events, eid = _assert_inherited(events, cik, key, content, support_path=REPO_PREFIX + item["path"],
                                        sha=item["sha256"], evidence=file_evidence(item["path"], item["sha256"], content),
                                        author=author, recorded_at=recorded_at)
        admissions[eid] = pd.admission("accepted", "inherited_production", source_kind="override_file",
                                       mechanism=family + " override file", confidence=_number(meta.get("confidence")),
                                       source_author=str(meta.get("created_by") or author), recorded_at=recorded_at,
                                       run_id=run_id, source=REPO_PREFIX + item["path"], witness={},
                                       inception_evaluation=NO_CONTRACT)
        targets.setdefault(item["path"], []).append(eid)
    pred = inputs["predicate"]
    events, basis_id = _assert_inherited(
        events, cik, "partition_structure.published_basis", {"predicate": pred["version"]},
        support_path=PREDICATE_CODE_PATH, sha=pred["code_sha256"],
        evidence=[dict(kind="code_file", path=PREDICATE_CODE_PATH, sha256=pred["code_sha256"])]
        + [dict(e) for e in ADOPTION_EVIDENCE], author="human", recorded_at=recorded_at)
    admissions[basis_id] = pd.admission(
        "accepted", "adopted_predicate", source_kind="predicate_code",
        mechanism="census published-basis predicate " + pred["version"], confidence=None, source_author="human",
        recorded_at=recorded_at, run_id=run_id, source=PREDICATE_CODE_PATH,
        witness={"adoption": "anchor-aware adoption rule, controller rulings 3-4"},
        inception_evaluation="adoption rule over 101 fund-quarters of the 8 filers (IN-SAMPLE)")
    entities_id = None
    wrappers = files.get("bdc_xbrl_wrappers") or []
    if wrappers:
        w = wrappers[0]
        present, suffixes = _get(w["content"], REPORTING_ENTITY_POINTER)
        if present:
            evidence = file_evidence(w["path"], w["sha256"], w["content"], value_is_file=False,
                                     pointer=pointer(REPORTING_ENTITY_POINTER))
            evidence.append(dict(kind="investigation", path="docs/investigations/conservation_shadow_engine.md",
                                 heading="2026-10-01", note="R6 look-through rows by typed-identifier suffix"))
            events, entities_id = _assert_inherited(events, cik, "partition_structure.reporting_entities",
                                                    list(suffixes), support_path=REPO_PREFIX + w["path"],
                                                    sha=w["sha256"], evidence=evidence, author="human",
                                                    recorded_at=recorded_at)
            admissions[entities_id] = pd.admission(
                "accepted", "inherited_production", source_kind="override_file",
                mechanism="wrapper source_encodings.reporting_entity_suffixes", confidence=None, source_author="human",
                recorded_at=recorded_at, run_id=run_id, source=REPO_PREFIX + w["path"], witness={},
                inception_evaluation="consistency contract vs wrapper and the census_published code mirror")
            targets.setdefault(w["path"], []).append(entities_id)
    entries = envelope.materialize_entries(events)
    live_keys = [e["key"] for e in entries if e["recorded_until"] is None]
    dup = sorted({k for k in live_keys if live_keys.count(k) > 1})
    if dup:
        raise InceptionError("two inception entries for one key: " + repr(dup))
    blocks = []
    for family, block_family in (("bdc_xbrl_wrappers", "bdc_xbrl_wrapper"),
                                 ("agent_investigate_rules", "agent_investigate_rules")):
        found = files.get(family) or []
        if not found:
            continue
        tags = sorted({t for x in found for t in (inputs.get("attested_under") or {}).get(x["path"], [])})
        block = wrapper_block(cik, family=block_family, files=found, recorded_at=recorded_at, attested_under=tags)
        blocks.append(block)
        for x in found:
            targets.setdefault(x["path"], []).append(block["block_id"])
    corrections = correction_records(cik, b2_files=files.get("agent_b2_corrections") or [],
                                     shared=inputs.get("shared") or {}, recorded_at=recorded_at, run_id=run_id)
    for c in corrections:
        targets.setdefault(c["source"]["path"], []).append(c["correction_id"])
    disposition = []
    for d in inputs["disposition"]:
        d = dict(d, targets=list(targets.get(d["path"], [])))
        if d["action"] in ("entry", "wrapper_block", "correction") and not d["targets"]:
            raise InceptionError("converted file produced nothing: " + d["path"])
        disposition.append(d)
    stubs = grid_stubs(cik, entries, admissions, census_stubs, report_date=pd.INCEPTION_REPORT_DATE,
                       census_unavailable=inputs.get("census_q4_unavailable"))
    detection = {k: dict(claim="claimed" if v["verdict"] == "PASS" else "detection_not_claimed",
                         verdict=v["verdict"], replay_run_id=v["replay_run_id"])
                 for k, v in sorted((inputs.get("detection") or {}).items())}
    q4, q1 = inputs.get("census_q4"), inputs.get("census_q1")
    doc = dict(
        schema=pd.SCHEMA_NAME, schema_version=1, document_version=1, cik=cik,
        inception_report_date=pd.INCEPTION_REPORT_DATE, recorded_at=recorded_at, run_id=run_id,
        code=dict(git_head=git_head, converter_version=pd.CONVERTER_VERSION),
        events=events, entries=entries, admissions=admissions, stubs=stubs,
        wrapper_section=dict(blocks=blocks), corrections=corrections,
        partition_predicate=dict(census_published_version=pred["version"], published_basis_entry_id=basis_id,
                                 reporting_entities_entry_id=entities_id,
                                 code_mirror=dict(path=PREDICATE_CODE_PATH, constant="REPORTING_ENTITIES",
                                                  value=list(inputs.get("code_mirror") or []))),
        detection_claims=detection, disposition=disposition,
        ledger=[dict(event="document_created", at=recorded_at, run_id=run_id, detail=dict(
            converter_version=pd.CONVERTER_VERSION,
            census_q4=q4["source"]["census_relative"] if q4 else None,
            census_q1=q1["source"]["census_relative"] if q1 else None,
            census_q4_unavailable=inputs.get("census_q4_unavailable"),
            overrides_root=inputs.get("overrides_root"), replay_run_id=inputs.get("replay_run_id")))])
    pd.validate_document(doc)
    return doc
```

- [ ] **Step 4: Run to pass** (`sp3p-verify-t6b`): `tests/test_profile_pilot_profile_inception.py tests/test_profile_pilot_profile.py tests/test_profile_pilot_profile_document.py`.
- [ ] **Step 5: Commit** `Build inception profile documents from override files and the Q4-2025 census`.

### Task 7: Round trip (profile -> override shapes == originals) and production-loader parity

**Files:**
- Create: `scripts/profile_pilot/profile_roundtrip.py`
- Test: `tests/test_profile_pilot_profile_roundtrip.py` (new)

**Interfaces:**
- Consumes: documents from `profile_inception.build_document` (Task 6); `profile_families.scan_overrides/collect_override_inputs/read_json/SHARED_FILES/cik10/REPO_PREFIX` (Task 4); production loaders `pipeline.agent_promoted.load_promoted_corrections(dir)`, `load_promoted_rules(dir)`, `pipeline.rate_convention.load_convention_overrides(dir)`, `translate.admit_directory(dir, ciks, base_dir=)` (read-only, directory-parameterised).
- Produces:

```python
CONVERTED_ACTIONS = ("entry", "wrapper_block", "correction")
class RoundTripError(ValueError)
def materialise_overrides(documents: list[dict], *, shared_originals: dict[str, object]) -> dict[str, object]
    # relative path (under data/overrides) -> parsed content, key order preserved; shared files spliced
def expected_paths(documents) -> list[str]        # sorted paths whose disposition action is converted
def roundtrip_check(materialised: dict, originals: dict) -> dict
    # {"ok": bool, "counts": {"identical","differs","missing","extra"}, "files": {path: status}, "comparison": str}
def loader_parity(original_root: Path, materialised_root: Path, ciks) -> dict
    # {"bdc_xbrl_wrappers": {cik: bool}, "agent_b2_corrections": bool, "agent_investigate_rules": {cik: bool},
    #  "rate_convention": {cik: bool}, "ok": bool, "not_loader_checked": [...], "note": str}
```

What is regenerated from where: whole-file inherited entries (evidence `override_file` with `value_is_file: true`) -> their file; `bdc_xbrl_wrapper` block -> its source file; `agent_investigate_rules` block -> each file in `content.files`; corrections with `record_index = null` -> their file; corrections with a `record_index` -> spliced back into the shared file at that index (every non-pilot record kept as is; the pilot records must tile exactly the removed indexes, else `RoundTripError`). Identity is order-preserving parsed JSON; raw bytes are NOT claimed identical (main has CRLF files and mixed indentation; neither is behaviour).

- [ ] **Step 1: Failing tests** (`tests/test_profile_pilot_profile_roundtrip.py`):

```python
"""SP3 proper Task 7: documents -> override shapes identical to the originals; production loader parity.

The real-shape test reads the worktree's git-tracked data/overrides (read-only) for the 8 pilot filers and writes
only under tmp_path. If the scan raises FamilyError on the real tree, STOP and report it: the disposition table is
not widened inside this task."""
from __future__ import annotations

import json

import pytest

from scripts.profile_pilot import cohort
from scripts.profile_pilot import profile_families as pf
from scripts.profile_pilot import profile_inception as pi
from scripts.profile_pilot import profile_roundtrip as rt
from tests.test_profile_pilot_paths import CODE_ROOT
from tests.test_profile_pilot_profile_families import STELLUS
from tests.test_profile_pilot_profile_inception import NOW, RUN, SHA, inception_inputs

REAL = CODE_ROOT / "data" / "overrides"
ORACLE = "bdc_xbrl_oracle_exceptions.json"


def synthetic():
    mine = {"cik": STELLUS, "report_date": "2025-12-31", "oracle_reason": "rate_outliers_detected"}
    original = [{"cik": "0001111111", "report_date": "2024-12-31", "oracle_reason": "x"}, mine,
                {"cik": "0002222222", "report_date": "2025-03-31", "oracle_reason": "y"}]
    inputs = inception_inputs(shared={ORACLE: {"sha256": SHA, "records": [[1, mine]]}})
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    originals = {x["path"]: x["content"] for items in inputs["files"].values() for x in items}
    originals[ORACLE] = original
    return doc, originals, {ORACLE: original}


def test_synthetic_round_trip_is_identical():
    doc, originals, shared = synthetic()
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals=shared), originals)
    assert out["ok"] and out["counts"] == {"identical": 3, "differs": 0, "missing": 0, "extra": 0}
    assert rt.expected_paths([doc]) == sorted(originals)


def test_key_order_change_is_a_difference():
    doc, originals, shared = synthetic()
    block = doc["wrapper_section"]["blocks"][0]
    rules = block["content"]["dispatch"]["prefix_rules"]
    block["content"]["dispatch"]["prefix_rules"] = dict(reversed(list(rules.items())))
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals=shared), originals)
    assert not out["ok"] and out["files"]["bdc_xbrl_wrappers/" + STELLUS + ".json"] == "differs"


def test_missing_pilot_record_breaks_the_tiling():
    doc, _, shared = synthetic()
    doc["corrections"] = []
    with pytest.raises(rt.RoundTripError, match="tile"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_missing_and_extra_files_are_reported():
    out = rt.roundtrip_check({"a.json": {}}, {"b.json": {}})
    assert out["files"] == {"a.json": "extra", "b.json": "missing"} and not out["ok"]


def real_documents():
    hits = pf.scan_overrides(REAL, cohort.PILOT_CIKS)
    docs = []
    for cik in cohort.PILOT_CIKS:
        inputs = pf.collect_override_inputs(REAL, cik, hits)
        inputs.update(attested_under={}, census_q4=None, census_q4_unavailable=None, census_q1=None, detection={},
                      predicate=dict(version="census-published.v2", code_sha256="0" * 64), code_mirror=[],
                      overrides_root="worktree data/overrides", replay_run_id="none")
        docs.append(pi.build_document(cik, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9"))
    return docs


def test_real_tracked_overrides_round_trip_and_load_identically(tmp_path):
    docs = real_documents()
    shared = {n: pf.read_json(REAL / n) for n in pf.SHARED_FILES if (REAL / n).is_file()}
    mat = rt.materialise_overrides(docs, shared_originals=shared)
    originals = {rel: pf.read_json(REAL / rel) for rel in rt.expected_paths(docs)}
    result = rt.roundtrip_check(mat, originals)
    assert result["ok"], {k: v for k, v in result["files"].items() if v != "identical"}
    assert result["counts"]["identical"] >= 30
    root = tmp_path / "materialised"
    for rel, value in mat.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    parity = rt.loader_parity(REAL, root, cohort.PILOT_CIKS)
    assert parity["ok"], parity
    assert set(parity["bdc_xbrl_wrappers"]) == set(cohort.PILOT_CIKS)
```

- [ ] **Step 2: Run to fail** (`sp3p-verify-t7a`).

- [ ] **Step 3: Implement** `scripts/profile_pilot/profile_roundtrip.py`:

```python
"""SP3 proper: regenerate the override shapes from profile documents and prove they equal the originals.

This is the guard that inception cannot change production silently: every converted override file (spec 7.1
dispositions entry / wrapper_block / correction) is rebuilt from the documents and compared with the file read,
order-preserving (dispatch.prefix_rules order is behaviour), and the directory-parameterised production loaders are
run on both trees. Shared files are spliced: non-pilot records stay as read; the pilot records come back from the
corrections at their recorded index and must tile the removed indexes exactly. No file under data/overrides is
written; the CLI writes the materialised tree only under its run root.
"""
from __future__ import annotations

import copy
from pathlib import Path

from scripts.profile_pilot import envelope
from scripts.profile_pilot.profile_families import REPO_PREFIX, cik10
from scripts.profile_pilot.translate import value_sha256

CONVERTED_ACTIONS = ("entry", "wrapper_block", "correction")
COMPARISON = ("order-preserving parsed JSON (translate.value_sha256); raw bytes are not compared "
              "(CRLF and indentation are not behaviour)")


class RoundTripError(ValueError):
    """The documents cannot regenerate the override files unambiguously."""


def _per_filer_files(document: dict) -> dict:
    out = {}

    def put(rel, value):
        if rel in out:
            raise RoundTripError(document["cik"] + " produces " + rel + " twice")
        out[rel] = copy.deepcopy(value)

    for e in envelope.materialize_entries(document["events"]):
        if e["recorded_until"] is not None or e["provenance"] != "inherited":
            continue
        for item in e["evidence"]:
            if item.get("kind") == "override_file" and item.get("value_is_file") is True:
                put(item["path"][len(REPO_PREFIX):], e["value"])
    for b in document["wrapper_section"]["blocks"]:
        if b["recorded_until"] is not None:
            continue
        if b["family"] == "bdc_xbrl_wrapper":
            put(b["source_files"][0]["path"], b["content"])
        else:
            for rel, rule in b["content"]["files"].items():
                put(rel, rule)
    for c in document["corrections"]:
        if c["recorded_until"] is None and c["source"]["record_index"] is None:
            put(c["source"]["path"], c["value"])
    return out


def _splice(records: list, ciks: set, items: list) -> list:
    keep = {i: r for i, r in enumerate(records) if cik10(r.get("cik")) not in ciks}
    for index, record in items:
        if index in keep:
            raise RoundTripError("record index " + str(index) + " is not a pilot record of the original")
        keep[index] = record
    if sorted(keep) != list(range(len(records))):
        raise RoundTripError("pilot records do not tile the original; missing indexes "
                             + repr(sorted(set(range(len(records))) - set(keep))[:5]))
    return [copy.deepcopy(keep[i]) for i in range(len(records))]


def materialise_overrides(documents: list, *, shared_originals: dict) -> dict:
    out, items = {}, {}
    ciks = {d["cik"] for d in documents}
    for doc in documents:
        for rel, value in _per_filer_files(doc).items():
            if rel in out:
                raise RoundTripError("two documents produce " + rel)
            out[rel] = value
        for c in doc["corrections"]:
            if c["recorded_until"] is None and c["source"]["record_index"] is not None:
                items.setdefault(c["source"]["path"], []).append((c["source"]["record_index"], c["value"]))
    for name in sorted(set(items) | set(shared_originals)):
        if name not in shared_originals:
            raise RoundTripError("no original read for shared file " + name)
        original = shared_originals[name]
        records = original["overrides"] if isinstance(original, dict) else original
        spliced = _splice(records, ciks, items.get(name, []))
        out[name] = dict(original, overrides=spliced) if isinstance(original, dict) else spliced
    return out


def expected_paths(documents) -> list:
    return sorted({d["path"] for doc in documents for d in doc["disposition"] if d["action"] in CONVERTED_ACTIONS})


def roundtrip_check(materialised: dict, originals: dict) -> dict:
    files = {}
    for rel in sorted(set(materialised) | set(originals)):
        if rel not in materialised:
            files[rel] = "missing"
        elif rel not in originals:
            files[rel] = "extra"
        else:
            same = value_sha256(materialised[rel]) == value_sha256(originals[rel])
            files[rel] = "identical" if same else "differs"
    counts = {s: sum(v == s for v in files.values()) for s in ("identical", "differs", "missing", "extra")}
    return dict(ok=bool(files) and counts["identical"] == len(files), counts=counts, files=files,
                comparison=COMPARISON)


def _digests(items) -> list:
    return sorted(value_sha256(i) for i in items)


def loader_parity(original_root, materialised_root, ciks) -> dict:
    from pipeline import agent_promoted, rate_convention
    from scripts.profile_pilot import translate
    original_root, materialised_root = Path(original_root), Path(materialised_root)
    ciks = sorted(cik10(c) for c in ciks)
    out = {}
    wrappers = translate.admit_directory(materialised_root / "bdc_xbrl_wrappers", ciks,
                                         base_dir=original_root / "bdc_xbrl_wrappers")
    out["bdc_xbrl_wrappers"] = {
        c: bool(v.get("admitted")) and (v.get("spec_parity") or {}).get("equal") is True
        for c, v in wrappers["ciks"].items() if (original_root / "bdc_xbrl_wrappers" / (c + ".json")).is_file()}
    orig = [leaf for leaf in agent_promoted.load_promoted_corrections(original_root / "agent_b2_corrections")
            if cik10(leaf.get("cik")) in ciks]
    mat = agent_promoted.load_promoted_corrections(materialised_root / "agent_b2_corrections")
    out["agent_b2_corrections"] = _digests(orig) == _digests(mat)
    orig_rules = agent_promoted.load_promoted_rules(original_root / "agent_investigate_rules")
    mat_rules = agent_promoted.load_promoted_rules(materialised_root / "agent_investigate_rules")
    out["agent_investigate_rules"] = {c: _digests(orig_rules.get(c, [])) == _digests(mat_rules.get(c, []))
                                      for c in ciks}
    orig_conv = rate_convention.load_convention_overrides(original_root / "rate_convention")
    mat_conv = rate_convention.load_convention_overrides(materialised_root / "rate_convention")
    out["rate_convention"] = {c: value_sha256(orig_conv.get(str(int(c)))) == value_sha256(mat_conv.get(str(int(c))))
                              for c in ciks}
    flat = [v for v in out.values() if isinstance(v, bool)]
    flat += [x for v in out.values() if isinstance(v, dict) for x in v.values()]
    out["ok"] = all(flat)
    out["not_loader_checked"] = ["identifier_rate_grammars", "identifier_anchors",
                                 "bdc_aggregate_row_overrides.json", "bdc_xbrl_oracle_exceptions.json"]
    out["note"] = ("families without a directory-parameterised production loader are covered by the "
                   "order-preserving file round trip only")
    return out
```

- [ ] **Step 4: Run to pass** (`sp3p-verify-t7b`): `tests/test_profile_pilot_profile_roundtrip.py tests/test_profile_pilot_profile_inception.py`. Record in the SDD ledger the real-shape counts (`identical`, files per family).
- [ ] **Step 5: Commit** `Prove profile documents regenerate the override files and load identically`.

### Task 8: Consistency contract (D-precedence) and the sub-project 3 exit test

**Files:**
- Create: `scripts/profile_pilot/profile_consistency.py`
- Test: `tests/test_profile_pilot_profile_consistency.py` (new)

**Interfaces:**
- Consumes: `profile_document.resolve/coverage/GRID_KEYS/ProfileAmbiguityError` (Task 3); `translate.TRANSLATIONS/_convert/_get/pointer/value_sha256` (the Task 7 adapter is the comparator, spec 4.1); documents (Task 6); roundtrip result (Task 7).
- Produces:

```python
COUNTERPARTS: tuple[dict, ...]       # translate.TRANSLATIONS + source_encodings.reporting_entity_suffixes
COMPARE_MODE: dict[str, str]         # pointer -> exact | exact_set | token ; default representation
CODE_MIRROR_POINTER = "code:scripts/profile_pilot/census_published.py:REPORTING_ENTITIES"
EXIT_TEST_TEXT = "criterion 1; resolver answers every field; consistency contract holds on all 8"
def consistency_contract(document: dict, *, report_date: str, code_mirror=()) -> dict
    # {"cik", "report_date", "block_id", "evaluated_dates", "unevaluated", "keys": [row], "counts", "verdict"}
    # row: {"pointer", "profile_key", "mode", "resolution", "entry_id", "stub_cause", "status", "reason", ...}
def coverage_report(document: dict, report_date: str) -> dict     # {"ok", "missing", "cells", "stubs", "entries"}
def resolver_report(document: dict, report_date: str) -> dict     # {"ok", "counts", "no_entry", "ambiguous"}
def exit_test(documents: dict, consistency: dict, roundtrip: dict, *, report_date: str, expected_ciks) -> dict
    # {"report_date", "spec_exit_test", "spec_exit", "precondition_roundtrip", "missing_filers", "verdict",
    #  "n_filers", "per_cik", "sample_label": "IN-SAMPLE"}
```

Status rules per key (P11): wrapper lacks the key -> `not_applicable`; key present but no ACCEPTED entry -> `insufficient_evidence` (reason names the stub cause); entry value not expressible in wrapper shape (`translate._convert` returns no `via`) -> `insufficient_evidence`; otherwise compare by mode: `exact`/`exact_set`/`token` -> holds or `breach`; `representation` -> holds or `insufficient_evidence` (`representation_mismatch`). Code mirror row: entry resolved -> holds iff sorted values equal, else breach; no entry -> breach if the mirror is non-empty, else not_applicable. Filer verdict `holds` iff zero breaches (no live wrapper block -> `insufficient_evidence`).

- [ ] **Step 1: Failing tests** (`tests/test_profile_pilot_profile_consistency.py`):

```python
"""SP3 proper Task 8: consistency contract (spec 4.1) and the sub-project 3 exit test (spec 8 row 3)."""
from __future__ import annotations

import copy

from scripts.profile_pilot import profile_consistency as pc
from scripts.profile_pilot import profile_inception as pi
from tests.test_profile_pilot_profile_families import ARES, STELLUS, wrapper_v3
from tests.test_profile_pilot_profile_inception import NOW, Q4, RUN, inception_inputs

ENTS = ["Emerald JV LP"]


def doc_with(wrapper=None):
    inputs = inception_inputs(wrapper=wrapper)
    return pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def rows(result):
    return {r["pointer"]: r for r in result["keys"]}


def test_agreeing_wrapper_holds():
    out = pc.consistency_contract(doc_with(), report_date=Q4, code_mirror=ENTS)
    r = rows(out)
    assert out["verdict"] == "holds" and out["counts"]["breach"] == 0
    assert r["/identifier_format/delimiter"]["status"] == "holds"
    assert r["/source_encodings/reporting_entity_suffixes"]["status"] == "holds"
    assert r[pc.CODE_MIRROR_POINTER]["status"] == "holds"
    assert r["/invariants/fv_reconciliation/source_field"]["status"] == "not_applicable"
    assert out["evaluated_dates"] == [Q4] and out["unevaluated"]["block_valid"] == [None, None]


def test_delimiter_disagreement_is_a_breach():
    w = wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ENTS})
    w["identifier_format"]["delimiter"] = "; "
    out = pc.consistency_contract(doc_with(w), report_date=Q4, code_mirror=ENTS)
    assert out["verdict"] == "breach"
    assert rows(out)["/identifier_format/delimiter"]["reason"] == "value_disagrees"


def test_code_mirror_disagreement_or_orphan_is_a_breach():
    out = pc.consistency_contract(doc_with(), report_date=Q4, code_mirror=["Other JV LP"])
    assert rows(out)[pc.CODE_MIRROR_POINTER]["status"] == "breach"
    bare = doc_with(wrapper_v3(STELLUS))           # no source_encodings -> no reporting-entities entry
    out = pc.consistency_contract(bare, report_date=Q4, code_mirror=ENTS)
    assert rows(out)[pc.CODE_MIRROR_POINTER]["status"] == "breach"
    assert pc.consistency_contract(bare, report_date=Q4, code_mirror=())["verdict"] == "holds"


def test_compare_modes():
    assert pc._compare("token", " | ", "|") == "holds"
    assert pc._compare("token", " | ", " ; ") == "breach"
    assert pc._compare("exact_set", ["b", "a"], ["a", "b"]) == "holds"
    assert pc._compare("representation", ["total investments"], ["Total Investments"]) == "insufficient_evidence"
    assert pc._compare("exact", "0001901037", "0001901038") == "breach"


def test_exit_test_pass_and_failures():
    doc = doc_with()
    con = {STELLUS: pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)}
    ok_rt = {"ok": True}
    out = pc.exit_test({STELLUS: doc}, con, ok_rt, report_date=Q4, expected_ciks=(STELLUS,))
    assert out["verdict"] == "PASS" and out["spec_exit"] is True and out["per_cik"][STELLUS]["resolver"] is True
    assert out["per_cik"][STELLUS]["resolved"] + out["per_cik"][STELLUS]["stubs"] == 56
    assert pc.exit_test({STELLUS: doc}, con, ok_rt, report_date=Q4,
                        expected_ciks=(STELLUS, ARES))["missing_filers"] == [ARES]
    assert pc.exit_test({STELLUS: doc}, con, {"ok": False}, report_date=Q4,
                        expected_ciks=(STELLUS,))["verdict"] == "FAIL"
    holed = copy.deepcopy(doc)
    holed["stubs"] = [s for s in holed["stubs"] if s["key"] != "income_proofs.duration"]
    bad = pc.exit_test({STELLUS: holed}, con, ok_rt, report_date=Q4, expected_ciks=(STELLUS,))
    assert bad["verdict"] == "FAIL"
    assert bad["per_cik"][STELLUS]["coverage_missing"] == ["income_proofs.duration"]
    assert bad["per_cik"][STELLUS]["resolver_no_entry"] == ["income_proofs.duration"]
```

- [ ] **Step 2: Run to fail** (`sp3p-verify-t8a`).

- [ ] **Step 3: Implement** `scripts/profile_pilot/profile_consistency.py`:

```python
"""SP3 proper: consistency contract between entries and the wrapper section (spec 4.1, D-precedence) and the
sub-project 3 exit test (spec 8 row 3).

Entries are authoritative on meaning, the wrapper on procedure. For every wrapper key with a semantic counterpart
(translate.TRANSLATIONS plus source_encodings.reporting_entity_suffixes) the ACCEPTED entry resolved at the report
date is converted to wrapper shape by the Task 7 adapter's converter and compared. Exact keys (cik, fv source field,
reporting entities; delimiter by stripped token) can breach; other keys report a representation mismatch as
insufficient_evidence (spec 10). A missing accepted entry is insufficient_evidence, never a silent pass. The
census_published code mirror of the reporting-entity list is a third party to the same comparison. Evaluated at the
inception report date only (inception entries start there); the rest of the wrapper block's validity is recorded as
unevaluated. A breach blocks the filer and is resolved by superseding the wrong side, never by editing the other.
"""
from __future__ import annotations

from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot.translate import TRANSLATIONS, _convert, _get, pointer, value_sha256

COUNTERPARTS = tuple(dict(t) for t in TRANSLATIONS) + (
    dict(wrapper_path=("source_encodings", "reporting_entity_suffixes"),
         profile_key="partition_structure.reporting_entities", convert="string_list"),)
COMPARE_MODE = {"/cik": "exact", "/invariants/fv_reconciliation/source_field": "exact",
                "/source_encodings/reporting_entity_suffixes": "exact_set", "/identifier_format/delimiter": "token"}
CODE_MIRROR_POINTER = "code:scripts/profile_pilot/census_published.py:REPORTING_ENTITIES"
STATUSES = ("holds", "breach", "insufficient_evidence", "not_applicable")
EXIT_TEST_TEXT = "criterion 1; resolver answers every field; consistency contract holds on all 8"


def _compare(mode: str, wrapper_value, converted) -> str:
    if mode == "exact":
        return "holds" if value_sha256(wrapper_value) == value_sha256(converted) else "breach"
    if mode == "exact_set":
        return "holds" if sorted(map(str, wrapper_value or [])) == sorted(map(str, converted or [])) else "breach"
    if mode == "token":
        return "holds" if str(wrapper_value).strip() == str(converted).strip() else "breach"
    return "holds" if value_sha256(wrapper_value) == value_sha256(converted) else "insufficient_evidence"


def consistency_contract(document: dict, *, report_date: str, code_mirror=()) -> dict:
    blocks = [b for b in document["wrapper_section"]["blocks"]
              if b["family"] == "bdc_xbrl_wrapper" and b["recorded_until"] is None]
    base = dict(cik=document["cik"], report_date=report_date, evaluated_dates=[report_date])
    if len(blocks) != 1:
        return dict(base, block_id=None, unevaluated=None, keys=[], counts={s: 0 for s in STATUSES},
                    verdict="insufficient_evidence")
    block = blocks[0]
    out_rows = []
    for spec in COUNTERPARTS:
        ptr = pointer(spec["wrapper_path"])
        present, wvalue = _get(block["content"], spec["wrapper_path"])
        res = pd.resolve(document, spec["profile_key"], report_date)
        row = dict(pointer=ptr, profile_key=spec["profile_key"], mode=COMPARE_MODE.get(ptr, "representation"),
                   resolution=res["status"], entry_id=(res.get("entry") or {}).get("entry_id"),
                   stub_cause=(res.get("stub") or {}).get("cause"))
        if not present:
            row.update(status="not_applicable", reason="wrapper has no key")
        elif res["status"] != "resolved":
            row.update(status="insufficient_evidence", reason="no accepted entry (" + str(row["stub_cause"]) + ")",
                       wrapper_value=wvalue)
        else:
            converted, via, detail = _convert(spec, res["entry"]["value"])
            if via is None:
                row.update(status="insufficient_evidence", reason="no_wrapper_representation: " + str(detail),
                           wrapper_value=wvalue)
            else:
                status = _compare(row["mode"], wvalue, converted)
                row.update(status=status, wrapper_value=wvalue, entry_value_as_wrapper=converted,
                           reason=None if status == "holds" else
                           ("representation_mismatch" if status == "insufficient_evidence" else "value_disagrees"))
        out_rows.append(row)
    mirror = sorted(str(v) for v in code_mirror)
    res = pd.resolve(document, "partition_structure.reporting_entities", report_date)
    if res["status"] == "resolved":
        status = "holds" if sorted(map(str, res["entry"]["value"])) == mirror else "breach"
        reason = None if status == "holds" else "code mirror differs from the entry"
    else:
        status = "breach" if mirror else "not_applicable"
        reason = "code mirror carries per-filer knowledge with no accepted entry" if mirror else "no list anywhere"
    out_rows.append(dict(pointer=CODE_MIRROR_POINTER, profile_key="partition_structure.reporting_entities",
                         mode="exact_set", resolution=res["status"],
                         entry_id=(res.get("entry") or {}).get("entry_id"),
                         stub_cause=(res.get("stub") or {}).get("cause"), status=status, reason=reason,
                         code_value=mirror))
    counts = {s: sum(r["status"] == s for r in out_rows) for s in STATUSES}
    return dict(base, block_id=block["block_id"],
                unevaluated=dict(block_valid=[block["valid_from"], block["valid_to"]],
                                 reason="inception entries start at " + report_date
                                        + "; other report dates of the block are not evaluated in sub-project 3"),
                keys=out_rows, counts=counts, verdict="breach" if counts["breach"] else "holds")


def coverage_report(document: dict, report_date: str) -> dict:
    cells = pd.coverage(document, report_date)
    missing = [k for k, c in cells.items()
               if not c["entry_ids"] and not (c["stub"] and c["stub"]["closing_evidence"])]
    return dict(ok=not missing, missing=missing, cells=cells,
                stubs=sum(1 for c in cells.values() if c["stub"]),
                entries=sum(1 for c in cells.values() if c["entry_ids"]))


def resolver_report(document: dict, report_date: str) -> dict:
    counts, no_entry, ambiguous = {"resolved": 0, "stub": 0}, [], []
    for key in pd.GRID_KEYS:
        try:
            res = pd.resolve(document, key, report_date)
        except pd.ProfileAmbiguityError as exc:
            ambiguous.append(dict(key=key, error=str(exc)))
            continue
        if res["status"] == "no_entry":
            no_entry.append(key)
        else:
            counts[res["status"]] += 1
    return dict(ok=not no_entry and not ambiguous, counts=counts, no_entry=no_entry, ambiguous=ambiguous)


def exit_test(documents: dict, consistency: dict, roundtrip: dict, *, report_date: str, expected_ciks) -> dict:
    per = {}
    for cik in sorted(documents):
        doc = documents[cik]
        cov, res, con = coverage_report(doc, report_date), resolver_report(doc, report_date), consistency[cik]
        per[cik] = dict(criterion_1=cov["ok"], resolver=res["ok"], consistency=con["verdict"] == "holds",
                        coverage_missing=cov["missing"], resolver_no_entry=res["no_entry"],
                        resolver_ambiguous=res["ambiguous"], resolved=res["counts"]["resolved"],
                        stubs=res["counts"]["stub"], consistency_counts=con["counts"],
                        breaches=[r for r in con["keys"] if r["status"] == "breach"])
    missing = sorted(set(expected_ciks) - set(documents))
    spec_ok = (not missing and bool(per)
               and all(p["criterion_1"] and p["resolver"] and p["consistency"] for p in per.values()))
    return dict(report_date=report_date, spec_exit_test=EXIT_TEST_TEXT, spec_exit=spec_ok,
                precondition_roundtrip=bool(roundtrip.get("ok")), missing_filers=missing,
                verdict="PASS" if spec_ok and roundtrip.get("ok") else "FAIL", n_filers=len(per), per_cik=per,
                sample_label="IN-SAMPLE")
```

- [ ] **Step 4: Run to pass** (`sp3p-verify-t8b`): `tests/test_profile_pilot_profile_consistency.py tests/test_profile_pilot_translate.py`.
- [ ] **Step 5: Commit** `Add the entry-wrapper consistency contract and the SP3 exit test`.

### Task 9: `profile_document_run` CLI (launcher conventions, write-once run root)

**Files:**
- Create: `scripts/profile_pilot/profile_document_run.py`
- Test: `tests/test_profile_pilot_profile_document_run.py` (new)

**Interfaces:**
- Consumes: everything above; `lineage.load_authoritative_census(paths, run_id, roles=, ciks=, require_excluded=True)`; `manifest.file_record/verify_inputs/git/git_head/dirty_source_digest`; `paths.resolve_paths/discover_main_root/write_once_json`; `translate._write_once_ordered`; `protection.protected_session`; `cohort.PILOT_CIKS`; `census_published.CENSUS_PUBLISHED_VERSION/REPORTING_ENTITIES`.
- Produces:

```python
RUN_PREFIX = "sp3p-profile-"
def attested_under(main_root: Path, rel: str, content) -> list[str]     # tags in pi.SIGNOFF_TAGS whose blob matches
def run_stage(paths, *, census_run_id: str, replay_run_id: str, ciks=None, recorded_at=None) -> dict
    # summary {"run_id", "git_head", "verdict", "seconds", "roundtrip_counts", "loader_parity_ok", "per_cik",
    #          "missing_filers"}
def main(argv=None) -> int     # build; exit 0 PASS, 1 FAIL, 2 invalidated, 4 refused
```

Command: `python -m scripts.profile_pilot.profile_document_run build --data-root "<main>/data" --run-id sp3p-profile-<stamp> --census-run-id stageb2-sp1census-20260930t2235z --replay-run-id <sp1 replay run id> [--cik C ...]`. Run-root layout: `manifest.json` (inputs pinned, git head, scan hits), `profiles/<cik>.json`, `roundtrip/overrides/<path>`, `results/roundtrip.json`, `results/consistency.json`, `results/exit_test.json`, `verification/<stamp>_profile_document_preservation.json` (protected session receipt). A `--cik` subset run is allowed for debugging but its exit test is always FAIL (`missing_filers`): the exit test is about all 8.

- [ ] **Step 1: Failing tests** (`tests/test_profile_pilot_profile_document_run.py`):

```python
"""SP3 proper Task 9: profile_document_run on a fake main root (tmp_path only; git attestation stubbed)."""
from __future__ import annotations

import hashlib
import json

import pytest

from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot import profile_document_run as run
from scripts.profile_pilot.paths import PathError
from tests.test_profile_pilot_paths import CODE_ROOT, fake_paths
from tests.test_profile_pilot_profile_families import STELLUS, write_tree, wrapper_v3
from tests.test_profile_pilot_profile_inception import Q1, Q4, census

CENSUS_RUN, REPLAY_RUN, AT = "stageb2-fakecensus", "sp1-replay-fake", "2026-10-01T12:00:00Z"


def seed(paths):
    data = paths.data_root
    write_tree(data / "overrides", {
        "bdc_xbrl_wrappers/" + STELLUS + ".json": wrapper_v3(STELLUS),
        "rate_convention/" + STELLUS + ".json": {"cik": STELLUS, "convention": "all_in", "target_quarter": Q1},
        "bdc_xbrl_oracle_exceptions.json": [
            {"cik": "0001111111", "report_date": "2024-12-31", "oracle_reason": "x"},
            {"cik": STELLUS, "report_date": Q4, "oracle_reason": "rate_outliers_detected"}]})
    root = data / "pilot" / "filer_profile" / CENSUS_RUN
    rows = []
    for date in (Q4, Q1):
        rel = "census/" + STELLUS + "/" + date + ".json"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        body = dict(complete=True, identity=dict(fingerprint="f" * 64), result=census(date)["doc"])
        path.write_text(json.dumps(body), encoding="ascii")
        rows.append(dict(cik=STELLUS, role="all:" + date, report_date=date, census_relative=rel,
                         census_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), fingerprint="f" * 64,
                         validation_verdict="pass"))
    (root / "results").mkdir(parents=True)
    (root / "results" / "authoritative.json").write_text(json.dumps(dict(fund_quarters=rows)), encoding="ascii")
    (root / "results" / "excluded.json").write_text(json.dumps(dict(fund_quarters=[])), encoding="ascii")
    replay = data / "pilot" / "filer_profile" / REPLAY_RUN / "results"
    replay.mkdir(parents=True)
    floors = {"fill_rate": dict(verdict="NO_POSITIVES"), "independent_totals": dict(verdict="FAIL")}
    (replay / "replay_q4_q1.json").write_text(json.dumps(dict(floors=floors)), encoding="ascii")


@pytest.fixture
def staged(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="sp3p-profile-test")
    seed(paths)
    monkeypatch.setattr(run, "attested_under", lambda main_root, rel, content: [])
    return paths


def build(paths):
    return run.run_stage(paths, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN, ciks=[STELLUS], recorded_at=AT)


def test_build_writes_documents_roundtrip_and_exit_test(staged):
    summary = build(staged)
    rr = staged.run_root
    doc = pd.load_document(rr / "profiles" / (STELLUS + ".json"))
    assert list(doc["wrapper_section"]["blocks"][0]["content"]["dispatch"]["prefix_rules"]) == ["Second Lien",
                                                                                                "First Lien"]
    assert doc["detection_claims"]["fill_rate"]["claim"] == "detection_not_claimed"
    assert (rr / "roundtrip" / "overrides" / "bdc_xbrl_oracle_exceptions.json").is_file()
    roundtrip = json.loads((rr / "results" / "roundtrip.json").read_text(encoding="ascii"))
    assert roundtrip["ok"] is True and roundtrip["counts"]["differs"] == 0 and roundtrip["loader_parity"]["ok"]
    body = json.loads((rr / "results" / "exit_test.json").read_text(encoding="ascii"))
    assert body["per_cik"][STELLUS]["criterion_1"] and body["per_cik"][STELLUS]["resolver"]
    assert body["verdict"] == "FAIL" and len(body["missing_filers"]) == 7   # a one-filer run never claims the 8
    assert summary["verdict"] == "FAIL"
    pinned = json.loads((rr / "manifest.json").read_text(encoding="ascii"))["inputs"]
    assert any(i["label"] == "overrides/rate_convention/" + STELLUS + ".json" for i in pinned)


def test_rerun_on_the_same_run_id_is_refused(staged):
    build(staged)
    with pytest.raises(PathError):
        build(staged)


def test_run_id_prefix_is_enforced(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-profile-x")
    with pytest.raises(PathError, match="sp3p-profile-"):
        run.run_stage(paths, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN)
    assert run.main(["build", "--data-root", str(paths.data_root), "--main-root", str(paths.main_repo_root),
                     "--run-id", "stageb-profile-x", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN]) == run.EXIT_REFUSED


def test_no_production_module_reads_profile_documents():
    for path in (CODE_ROOT / "pipeline").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ("data/profiles", "profile_document", "profile_inception"):
            assert needle not in text, (str(path), needle)
```

- [ ] **Step 2: Run to fail** (`sp3p-verify-t9a`).

- [ ] **Step 3: Implement** `scripts/profile_pilot/profile_document_run.py`:

```python
"""SP3 proper CLI: build the inception profile documents for the pilot filers, regenerate the override shapes,
check consistency and write the sub-project 3 exit test.

    python -m scripts.profile_pilot.profile_document_run build --data-root D --run-id sp3p-profile-<stamp>
        --census-run-id stageb2-sp1census-20260930t2235z --replay-run-id <sp1 replay run id>
        [--main-root M] [--cik C ...]

Reads, pinned by sha256 and re-verified at the end (a change invalidates the stage, exit 2): every file of
<main>/data/overrides that mentions a pilot filer (the MAIN checkout's production overrides, not the worktree copy)
plus the shared override files, the census root's authoritative/excluded listings and its 2025-12-31 / 2026-03-31
census files, <data_root>/pilot/filer_profile/<replay>/results/replay_q4_q1.json and
scripts/profile_pilot/census_published.py. Sign-off attestation is a read-only `git show <tag>:<path>` in the main
checkout. Writes ONLY under <data_root>/pilot/filer_profile/<run_id>/ (write-once): manifest.json,
profiles/<cik>.json and roundtrip/overrides/<path> (order-preserving), results/{roundtrip,consistency,exit_test}.json.
No production reader is switched and nothing under data/overrides or data/output is written.
Exit codes: 0 exit test PASS, 1 FAIL (documents still written), 2 stage invalidated, 4 refused.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from scripts.profile_pilot import (census_published, cohort, lineage, manifest, profile_consistency,
                                   protection, translate)
from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot import profile_families as pf
from scripts.profile_pilot import profile_inception as pi
from scripts.profile_pilot import profile_roundtrip as rt
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import PathError, discover_main_root, resolve_paths, write_once_json

CODE_ROOT = Path(__file__).resolve().parents[2]
RUN_PREFIX = "sp3p-profile-"
EXIT_FAIL, EXIT_INVALIDATED, EXIT_REFUSED = 1, 2, 4
Q4, Q1 = pd.INCEPTION_REPORT_DATE, "2026-03-31"
ROLES = ("all:" + Q4, "all:" + Q1)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def default_run_id(now: datetime | None = None) -> str:
    return RUN_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")


def _check_prefix(run_id: str) -> None:
    if not run_id.startswith(RUN_PREFIX):
        raise PathError("run id must start with " + RUN_PREFIX + ": " + run_id)


def attested_under(main_root: Path, rel: str, content) -> list:
    tags = []
    for tag in pi.SIGNOFF_TAGS:
        done = manifest.git(Path(main_root), "show", tag + ":" + pf.REPO_PREFIX + rel, check=False)
        if done.returncode != 0:
            continue
        try:
            tagged = json.loads(done.stdout.decode("utf-8-sig"))
        except ValueError:
            continue
        if translate.value_sha256(tagged) == translate.value_sha256(content):
            tags.append(tag)
    return tags


def _census(census: dict, cik: str, role: str):
    row = census["rows"].get((cik, role))
    if row is None:
        return None
    outer = json.loads((Path(census["run_root"]) / row["census_relative"]).read_text(encoding="ascii"))
    if outer.get("identity", {}).get("fingerprint") != row["fingerprint"] or outer.get("complete") is not True:
        raise StageInvalidated("census identity differs from the authoritative listing: " + row["census_relative"])
    doc = outer["result"]
    return dict(doc=doc, source=dict(cik=cik, report_date=row["report_date"], role=role,
                                     census_relative=row["census_relative"], census_sha256=row["census_sha256"],
                                     fingerprint=row["fingerprint"],
                                     accession_number=doc["document"].get("accession_number"),
                                     form_type=doc["document"].get("form_type")))


def _unavailable(excluded: dict, cik: str, census_run_id: str) -> dict:
    for row in excluded.get("fund_quarters", []):
        if row.get("cik") == cik and row.get("report_date") == Q4:
            return dict(census_run_id=census_run_id, reason=str(row.get("reason")), detail=row.get("detail"))
    return dict(census_run_id=census_run_id, reason="not_listed", detail="no authoritative or excluded row")


def run_stage(paths, *, census_run_id: str, replay_run_id: str, ciks=None, recorded_at=None) -> dict:
    _check_prefix(paths.run_id)
    started = time.perf_counter()
    ciks = sorted(pf.cik10(c) for c in (ciks or cohort.PILOT_CIKS))
    recorded_at = recorded_at or _now()
    root = paths.main_repo_root / "data" / "overrides"
    hits = pf.scan_overrides(root, ciks)
    census = lineage.load_authoritative_census(paths, census_run_id, roles=ROLES, ciks=ciks, require_excluded=True)
    excluded = json.loads(Path(census["excluded"]["path"]).read_text(encoding="ascii"))
    replay_path = paths.data_root / "pilot" / "filer_profile" / replay_run_id / "results" / "replay_q4_q1.json"
    replay_record = manifest.file_record(replay_path, "replay/" + replay_run_id + "/results/replay_q4_q1.json")
    if replay_record["status"] != "present":
        raise StageInvalidated("replay result missing: " + str(replay_path))
    floors = json.loads(replay_path.read_text(encoding="ascii"))["floors"]
    detection = {k: dict(verdict=v["verdict"], replay_run_id=replay_run_id) for k, v in floors.items()}
    predicate_record = manifest.file_record(paths.code_root / pi.PREDICATE_CODE_PATH, "code/" + pi.PREDICATE_CODE_PATH)
    predicate = dict(version=census_published.CENSUS_PUBLISHED_VERSION, code_sha256=predicate_record["sha256"])
    shared_names = [n for n in pf.SHARED_FILES if (root / n).is_file()]
    hit_paths = {h["path"] for h in hits}
    pins = ([manifest.file_record(root / h["path"], "overrides/" + h["path"]) for h in hits]
            + [manifest.file_record(root / n, "overrides/" + n) for n in shared_names if n not in hit_paths]
            + [census["authoritative"], census["excluded"]] + census["files"] + [replay_record, predicate_record])
    git = dict(head=manifest.git_head(paths.code_root), dirty_source_digest=manifest.dirty_source_digest(paths.code_root))
    write_once_json(paths, "manifest.json", dict(
        stage="sp3_profile_document", run_id=paths.run_id, git=git, inputs=pins, census_run_id=census_run_id,
        replay_run_id=replay_run_id, overrides_root=str(root), recorded_at=recorded_at,
        converter_version=pd.CONVERTER_VERSION, ciks=ciks, hits=hits))
    documents = {}
    for cik in ciks:
        inputs = pf.collect_override_inputs(root, cik, hits)
        inputs["attested_under"] = {x["path"]: attested_under(paths.main_repo_root, x["path"], x["content"])
                                    for x in inputs["files"].get("bdc_xbrl_wrappers", [])}
        q4 = _census(census, cik, ROLES[0])
        inputs.update(census_q4=q4, census_q1=_census(census, cik, ROLES[1]),
                      census_q4_unavailable=None if q4 else _unavailable(excluded, cik, census_run_id),
                      detection=detection, predicate=predicate,
                      code_mirror=list(census_published.REPORTING_ENTITIES.get(cik, ())),
                      overrides_root="main checkout data/overrides", replay_run_id=replay_run_id)
        doc = pi.build_document(cik, inputs=inputs, recorded_at=recorded_at, run_id=paths.run_id,
                                git_head=git["head"])
        translate._write_once_ordered(paths, "profiles/" + cik + ".json", doc)
        documents[cik] = doc
    shared = {n: pf.read_json(root / n) for n in shared_names}
    materialised = rt.materialise_overrides(list(documents.values()), shared_originals=shared)
    for rel, value in materialised.items():
        translate._write_once_ordered(paths, "roundtrip/overrides/" + rel, value)
    originals = {rel: pf.read_json(root / rel) for rel in rt.expected_paths(documents.values())}
    originals.update(shared)
    roundtrip = rt.roundtrip_check(materialised, originals)
    roundtrip["loader_parity"] = rt.loader_parity(root, paths.run_root / "roundtrip" / "overrides", ciks)
    roundtrip["ok"] = roundtrip["ok"] and roundtrip["loader_parity"]["ok"]
    consistency = {cik: profile_consistency.consistency_contract(
        doc, report_date=Q4, code_mirror=census_published.REPORTING_ENTITIES.get(cik, ()))
        for cik, doc in documents.items()}
    exit_body = profile_consistency.exit_test(documents, consistency, roundtrip, report_date=Q4,
                                              expected_ciks=cohort.PILOT_CIKS)
    write_once_json(paths, "results/roundtrip.json", roundtrip)
    write_once_json(paths, "results/consistency.json", consistency)
    write_once_json(paths, "results/exit_test.json", exit_body)
    after = manifest.verify_inputs(dict(inputs=pins))
    if not after["ok"]:
        raise StageInvalidated("pinned inputs changed during the stage: " + json.dumps(after)[:400])
    return dict(run_id=paths.run_id, git_head=git["head"], verdict=exit_body["verdict"],
                seconds=round(time.perf_counter() - started, 1), roundtrip_counts=roundtrip["counts"],
                loader_parity_ok=roundtrip["loader_parity"]["ok"], missing_filers=exit_body["missing_filers"],
                per_cik={c: dict(criterion_1=p["criterion_1"], resolver=p["resolver"], consistency=p["consistency"],
                                 resolved=p["resolved"], stubs=p["stubs"], counts=p["consistency_counts"])
                         for c, p in exit_body["per_cik"].items()})


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("build")
    cmd.add_argument("--main-root", type=Path, default=None)
    cmd.add_argument("--data-root", type=Path, required=True)
    cmd.add_argument("--code-root", type=Path, default=None)
    cmd.add_argument("--run-id", default=None)
    cmd.add_argument("--census-run-id", required=True)
    cmd.add_argument("--replay-run-id", required=True)
    cmd.add_argument("--cik", action="append", default=None)
    args = parser.parse_args(argv)
    try:
        run_id = args.run_id or default_run_id()
        _check_prefix(run_id)
        main_root = args.main_root or discover_main_root(CODE_ROOT)
        paths = resolve_paths(main_repo_root=main_root, data_root=args.data_root,
                              code_root=args.code_root or CODE_ROOT, run_id=run_id)
        receipt = ("verification/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                   + "_profile_document_preservation.json")
        with protection.protected_session(paths, receipt=receipt):
            summary = run_stage(paths, census_run_id=args.census_run_id, replay_run_id=args.replay_run_id,
                                ciks=args.cik)
    except StageInvalidated as exc:
        print("STAGE INVALIDATED: " + _ascii(str(exc)))
        return EXIT_INVALIDATED
    except (PathError, pf.FamilyError) as exc:
        print("REFUSED: " + _ascii(str(exc)))
        return EXIT_REFUSED
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    return 0 if summary["verdict"] == "PASS" else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to pass** (`sp3p-verify-t9b`): `tests/test_profile_pilot_profile_document_run.py`.
- [ ] **Step 5: Full pilot regression through the launcher WITH the backstop** (one call, fresh id `sp3p-verify-t9c`, no `--no-pre-backstop`): every `tests/test_profile_pilot_*.py` file. Expected: all pass; the post-backstop divergence count equals the pre-backstop count of the same call (680 at the 2026-10-01 baseline state; whatever the pre count is, post must equal it). Record the receipt path in the ledger.
- [ ] **Step 6: Commit** `Add the profile_document_run CLI for the SP3 inception build`.

### Task 10: Real run on the 8 pilot filers, exit test, record

**Files:**
- Create (only on PASS): `data/profiles/<cik>.json` x 8 in the worktree (byte copies of the run root's documents)
- Modify: `docs/agent_changelog.md` (append), `docs/superpowers/specs/2026-09-29-filer-profile-programme-design.md` (section 8 row 3 note only), SDD ledger

- [ ] **Step 1: Preconditions.** Code committed (`git -C <worktree> status --short` shows no tracked changes under `scripts/` or `tests/`). No conflicting process: `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId, CommandLine` shows no pytest, `rebuild_outputs`, `pipeline.programme`, `contracts_run`, `m2_seed`, `m2_backtest`, `replay_report` or `profile_pilot` process (the 2026-10-01 SP3 v2 re-measure chain must have exited). Choose the replay: the newest `sp1-replay-*` run root under `<main>/data/pilot/filer_profile/` that a changelog entry records as final (at plan time `sp1-replay-final-20261001t1230z`; if the v2 chain produced a newer recorded replay, use it and say so in the ledger).

- [ ] **Step 2: Run** (alone):

```
python -m scripts.profile_pilot.profile_document_run build --data-root "<main>/data" --run-id sp3p-profile-<stamp> --census-run-id stageb2-sp1census-20260930t2235z --replay-run-id <replay id>
```

- [ ] **Step 3: Read the results against the pre-registered expectations** (recorded as they come out; nothing is tuned):
  - Round trip: every converted file `identical` (about 40 files: 8 wrappers, 14 live investigate rules, 4 B2 leaves, 2 conventions, 5 grammars, 5 anchors, 2 shared files) and `loader_parity.ok = true`. Anything else is a STOP: the converter would change production; fix the converter, never the override file.
  - Census: 6 filers with Q4 census entries; NexPoint 0001588272 and TCW 0001715933 `census_unavailable`.
  - Detection claims: every kind `detection_not_claimed` unless its replay verdict is `PASS` (none was on 2026-10-01).
  - Consistency: report per filer `holds/breach/insufficient_evidence/not_applicable` counts. A breach can only come from `/cik`, `/invariants/fv_reconciliation/source_field`, `/identifier_format/delimiter`, BCRED's reporting entities or the code mirror; each breach is listed with both values and is NOT resolved in this task.
  - Exit verdict PASS or FAIL as computed. On FAIL, the per-filer reasons (coverage missing, resolver no_entry/ambiguous, breaches, round trip) go to the ledger and the controller; no threshold or rule is changed to reach PASS.

- [ ] **Step 4: On PASS only**, copy each `profiles/<cik>.json` to the worktree's `data/profiles/<cik>.json` (PowerShell `Copy-Item`) and confirm `Get-FileHash` equals the run-root file for all 8. On FAIL, copy nothing.

- [ ] **Step 5: Changelog** (append to the worktree `docs/agent_changelog.md`): `## 2026-10-0X -- SP3 proper: filer profile documents v1 at inception (Q4-2025)` with: modules and schema added (`profile_document`, `profile_families`, `profile_inception`, `profile_roundtrip`, `profile_consistency`, `profile_document_run`, document schema v1), the additive envelope change (`inherited_file` support, author/status kwargs), the census predicate argument; run id and replay id; per-filer table (entries accepted/candidate, stubs by cause, corrections and recurrence groups, blocks, consistency counts); round-trip counts and loader parity; detection claims; exit verdict; the plan decisions P1-P11 in one line each; NOT done (reader flip, deletion of override files, pre-image check, recurring promotion, fleet); every number labelled IN-SAMPLE.

- [ ] **Step 6: Spec note**: append to section 8 row 3 (exit-test column untouched): `SP3 proper <DONE|FAILED> 2026-10-0X: run sp3p-profile-<stamp>; documents v1 for the 8 at 2025-12-31; round trip <n>/<n> identical, loader parity <ok>; consistency <holds 8/8 | breaches ...>; see changelog`.

- [ ] **Step 7: Ledger close** with the commit hash, run id and verdict. Commit (controller) `Record SP3 proper: inception profile documents for the 8 pilot filers`.

---

## Self-review

**1. Spec coverage**

| Spec requirement | Where |
|---|---|
| s4: one document per filer, version, schema version, event log | Task 3 (schema v1: `schema_version`, `document_version`, `events`, `ledger`) |
| s4: entries with field, applies_to, valid_from/to, recorded_at/until, evidence, provenance, confidence, status {candidate, accepted, superseded, retracted}; immutable; supersession | Task 1 (envelope reuse + inherited support), Task 3 (`admissions`, `entry_state`), P1/P2 |
| s4: semantic axes per field | Task 3 grid (`FIELD_KEYS`, `FILER_KEYS`, `AXIS_OF_SECTION`) |
| s4: wrapper section, versioned block, validity, hash, evidence (sign-off) | Task 5 `wrapper_block` (+ `attested_under`), Task 9 `attested_under` |
| s4: corrections section | Task 5 `correction_records` |
| s4: `resolve` returns one accepted entry or explicit ambiguity | Task 3 `resolve` / `ProfileAmbiguityError` |
| s4: inception from override files (value, citations, date, content hash as pre-image); census entry or stub when no file | Task 6 (`file_evidence`, `_assert_inherited`, `census_entries`, `grid_stubs`), P3 |
| s4.1: entries authoritative on meaning; consistency contract via the translate comparator; breach blocks; representation mismatch insufficient (s10) | Task 8 `consistency_contract`, P8/P11 |
| s4.2: one-off (valid_from == valid_to, pre-image) vs recurring (flagged, owner-tier promotion) | Task 5 (`kind`, `pre_image`, `mark_recurrence`), Task 3 validation, P4/P5 |
| s5: contracts frozen before SP2 are provisional; detection_not_claimed label | Task 3 admission `contract.status_basis`, Task 6 `detection_claims` |
| s5 / Task 0: partition predicate becomes profile entries; reporting-entity list moves out of code | Task 2, Task 6 (`partition_structure.*`), Task 8 code-mirror row, P9 |
| s7.1: every family has a disposition; unclassified family fails; process artifacts never produce rows; reversible mapping; files not deleted | Task 4 (`FAMILY_CLASSES`, fail-closed scan), Task 6 `disposition.targets`, Task 7 round trip, P5-P7 |
| s7 D-convention: storage unchanged | Global Constraints; `meaning.interest_rate` records the file only |
| s8 row 3 exit test: criterion 1; resolver answers every field; consistency holds on all 8 | Task 8 `exit_test` (+ `missing_filers`), Task 10 |
| s9 constraints (no network, write-once, ASCII, no inline python, commit before runs, launcher tests) | Global Constraints; Task 9 CLI; every Run step |
| s10 risks: inherited errors (pre-image hash), consistency false positives, recurring widening | file `sha256` + `ordered_sha256` in evidence/disposition; P11; recurrence flagged not promoted |
| Non-goals: no reader flip, fleet, re-measure | Non-goals section; Task 9 no-production-reader test |

Gaps knowingly left to later sub-projects (stated, not silent): criterion 5 pre-image check (SP6), recurring promotion (SP6, owner), consistency evaluation before 2025-12-31, census for NexPoint/TCW Q4-2025 (census selection), conversion of expressible investigate rules (SP6).

**2. Placeholder scan.** No TBD/TODO/"similar to". Every code step has code; every test step has test code; the only free values are run-id stamps and the replay id chosen by an explicit rule in Task 10 Step 1.

**3. Type consistency.** `admission(...)` / `stub(...)` shapes (Task 3) match the schema `$defs` and are the only constructors used in Tasks 6-8. `collect_override_inputs` output keys (`files`, `shared`, `disposition`) are the `inputs` keys `build_document` reads (Task 6) and the CLI fills (Task 9). Disposition records carry `cls`/`action`/`targets`/`record_indexes` in Task 4, Task 6 and the schema. Corrections carry `source.record_index` (Task 5), read by `materialise_overrides` (Task 7). Evidence `override_file.value_is_file` is written in Task 6 (`file_evidence`) and read in Task 7 (`_per_filer_files`). `valid_at` (Task 3) is used by Task 6 `grid_stubs`. `consistency_contract(..., code_mirror=)` and `exit_test(..., expected_ciks=)` signatures match their callers in Task 9 and the tests in Task 8. `RUN_PREFIX = "sp3p-profile-"` is enforced in `run_stage` and `main` and matches the Global Constraints.

## Amendments from the pre-flight scan (2026-10-01, controller rulings; binding for every task)

- A1 (X13, blocking): the Q1-2026 census role is `verified_era`, not `all:2026-03-31`. Task 9 looks census entries up under `verified_era`; Task 9 test data uses that role; Task 10 expectations include the count of accepted census entries.
- A2 (X14/F4): the ledger already exists; Task 1 appends, never creates.
- A3 (S1): a filer's consistency verdict is `holds` only when every counterpart wrapper key has an accepted entry; when there are zero breaches but some keys lack evidence the verdict is `no_breach`, and the insufficient-evidence key count is published beside it (ruling P4).
- A4 (S2): BCRED's `reporting_entity_identifier_suffixes` (read by production) joins the checked keys; `cash_identifiers` and `rate_sanity` are reported as `unevaluated` keys, never silently omitted.
- A5 (S3): in this sub-project "consolidation" means the wrapper content is in the document and reproduces the file exactly (Task 7); deleting the file and redirecting the loader is sub-project 4.
- A6 (S4): one-off corrections are reported in two groups, row-keyed (`row_id`) and non-row-keyed (shared-file records, some B2 corrections); both are kept.
- A7 (D1/F5): Task 9 guards the MAIN checkout's `data/overrides` (and `data/output`, `frontend/public/data`) read-only for the run, not only the worktree copy.
- A8 (D2): the Task 9 CLI declares a workload (census documents are 35-55 MB).
- A9 (D3): an empty delimiter after whitespace stripping is `insufficient_evidence`, not a breach.
- A10 (Task 6/F3): `CENSUS_KEYS` excludes `non_private_markers` and `prefix_rules` (the census cannot derive them).
- A11 (Task 9): `InceptionError`, `RoundTripError`, `ProfileDocumentError` map to exit code 2 with a one-line message.
- A12 (F2): `read_json` reads plain utf-8 exactly as `pipeline/bdc_xbrl_wrapper.py` does; the docstring says so.
- A13 (minor): Task 3's Interfaces block is read together with the schema constants its tests use; the oversize position-registry file gets a disposition row (`not_loaded`, size); near-duplicated helper blocks are shared via one helper where the implementer finds them.
