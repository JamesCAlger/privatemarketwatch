# Filer Profile Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shadow measurement pilot that derives dated, bitemporal filer profiles from cached XBRL instances for eight BDCs and reports the five metrics M1-M5 defined in the spec.

**Architecture:** A read-only package `scripts/profile_pilot/` that imports pipeline modules without modifying them. Census reads cached instances through `pipeline.context_inventory.scan_instance`; profile derivation, contracts, graduation, parity and half-life are separate modules each writing one JSON artifact under `data/pilot/filer_profile/`. Every detector emits `resolved` / `candidate` / `insufficient_evidence`; every entry carries `provenance` (`derived` or `inherited`) and two clocks.

**Tech Stack:** Python 3.11+, DuckDB 1.4 (in-process), lxml (via `context_inventory`), jsonschema 4.x, pandas (small frames only), pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-filer-profile-pilot-design.md` (v3, approved to start 2026-09-28). Read sections 2, 5, 6, 8, 9, 10, 14 before any task.

## Global Constraints

- Work ONLY in the worktree `.claude/worktrees/filer-profile-pilot` on branch `filer-profile-pilot`. Never `cd` to or edit the sealed main checkout (spec section 2; V13 closeout rubric rule 1 freezes `pipeline/`, `scripts/`, `tests/`, `schemas/`, `data/overrides/`, `data/reference/` there).
- No edits under `pipeline/`. Pipeline modules are imported read-only.
- The worktree has NO `data/raw/` and NO `data/output/` (both git-ignored). All cache and output reads go through `PilotPaths.data_root`, which resolves to the main checkout's `data/` directory (Task 1). Writes go ONLY to `<data_root>/pilot/filer_profile/`. Never write under `<data_root>/output/` or `frontend/public/data/`.
- No network. No model calls. No SEC downloads.
- ASCII-only log and print output (Windows cp1252).
- Heavy-job rule (spec section 10): before running census on Ares (0001287750) or BCRED (0001803498), or the all-quarter half-life stage, check for running `pytest`, `rebuild_outputs.py`, `pipeline.programme.bootstrap` processes and for the V13 controllers in `scratch/2026-09-16_refactor_continuation/` (main checkout). If any is running, stop and report. The runner enforces this (Task 11). Light stages (graduation, schemas, synthetic tests, census on Stellus / NexPoint / Fidelity / TCW / Onex / Stepstone) may run at any time.
- No pandas `.apply()` / `.iterrows()` on frames larger than 10K rows. Slice with DuckDB first.
- Tests that read cached instances or built outputs are marked `@pytest.mark.needs_cache` and skip when `PILOT_DATA_ROOT` cannot be resolved.
- Per-CIK CIK strings: 10-digit zero-padded everywhere in pilot JSON. Cache directories use the stripped form (`data/raw/filings/bdc_xbrl/1901037/000155837022016375.xml`).
- Commit after every task with a short subject and 2-4 bullet body. Do not push.
- After the full test run, run `python scripts/diff_outputs.py --semantic` from the MAIN checkout is NOT possible from the worktree (no outputs); instead the conftest protected-file snapshot covers `data/output/` of the worktree (empty). Record in the changelog that the backstop was not applicable.

## Facts verified against the repo on 2026-09-28 (do not re-derive)

- `pipeline.context_inventory.scan_instance(path, cik, quarter, *, max_bytes, max_contexts, max_facts, timeout_seconds) -> dict` with keys `contexts` (list), `counts` ({confirmed_position, aggregate, unresolved}), `document_period_ends` (sorted list of period-end strings), `source_complete`, `errors`, `sha256`. It KEEPS ONLY contexts whose period equals `quarter` and that carry at least one mapped/suspicious fact. Each context dict: `context_id, period, period_kind, entity_cik, dimensions[{axis, axis_namespace, value, kind('typed'|'explicit'), member_namespace}], facts[{field, concept, fact_id, raw_text, value, value_status, unit_ref, unit_measures, currency, decimals}], unknown_concepts, extractor_recognized, role, role_reason`. `classify_context` imports `explicit_member_dimensions` from `pipeline.explicit_contexts` (per-CIK authored identity rules) -> INHERITED.
- `bdc_holdings.csv` columns: `period, investment_identifier, industry, investment_type, affiliation, dimensions_raw, acquisition_date, basis_spread, cost, face_amount, fair_value, interest_rate, interest_rate_floor, maturity_date, pct_of_net_assets, pik_rate, principal_amount, realized_gain_loss, reference_rate_type, shares_held, unrealized_gain_loss, fair_value_unit, cost_unit, principal_amount_unit, interest_rate_concept, src_facts, nonaccrual_footnote, nonaccrual_dimension, cik, entity_name, accession_number, form_type, filing_date, report_date, dedupe_context_count, dedupe_conflict_fields, dedupe_filled_fields, dedupe_axis_split, src_context_id`. NO `row_id`, NO `issuer_name`. Rates are DECIMAL (0.105 = 10.5%).
- `private_markets_holdings.csv` has `source, cik, accession_number, report_date, issuer_name, fair_value, bdc_investment_identifier, bdc_dimensions_raw, src_context_id, corrected_fields, is_subsidiary, row_id, position_id, index_classification, interest_rate, pik_rate` (rates in PERCENT).
- `bdc_filings_index.csv` columns: `cik, entity_name, accession_number, form_type, filing_date, report_date, primary_document, xbrl_download_status, xbrl_local_path`. `xbrl_download_status == 'cached'` marks an available instance. All 16 pilot fund-quarters are cached (checked 2026-09-28).
- `bdc_fund_income.csv` columns: `cik, entity_name, report_quarter, report_date, form_type, accession_number, start_date, end_date, duration_months, total_investment_income, interest_income, dividend_income, fee_income, other_income, net_investment_income, management_fee, incentive_fee, interest_expense, total_expenses`.
- Wrapper v3 JSON (`data/overrides/bdc_xbrl_wrappers/{cik10}.json`, tracked, present in the worktree): top-level `schema_version, cik, entity_name, version, source, dispatch{rule_prefix, prefix_rules, leaf_markers_by_family, aggregate_markers, non_private_markers, fallback_family_patterns, [category_marker_re, no_prefix_is_aggregate]}, staging{strategy, ...}, identifier_format{delimiter, field_order, alternate_delimiters}, archetypes{...}, invariants{fv_reconciliation, position_count_qoq, rate_sanity, unclassified_rate}, known_edge_cases[{id, description, first_seen_quarter, detection_pattern, disposition}], [segment_assertions], [source_encodings]`. Loaders: `pipeline.bdc_xbrl_wrapper._load_specs_from_json(directory)`, `reload_wrapper_specs(override_dir)` (overlays onto production, sets module global `WRAPPER_SPECS`; call with no arg to restore). `pipeline.staging_bdc._WRAPPER_DEFINITIONS_DIR` is a module constant read by `_load_staging_configs()` at `_prepare_bdc` time.
- Wrapper first-commit dates (git, worktree): Ares and Fidelity 2026-06-01; BCRED and Stellus 2026-06-04; Stepstone 2026-06-06; NexPoint, TCW, Onex 2026-06-11. Authoring quarter = latest cached `report_date` whose `filing_date <= wrapper add date` (expected 2026-03-31 for all eight).
- Corrections: B2 leaves at `data/overrides/agent_b2_corrections/{cik10}/{fix_class}.json` with keys `cik, mechanism, fix_class, scope{quarters}|template{report_date}, template, evidence_citations, confidence`. Investigate rules at `data/overrides/agent_investigate_rules/{cik_stripped}/{rule_id}.json` with `cik, rule_id, rule_type in {row_exclusion, row_add, dedup, value_rescale, value_expression}, action, scope{quarters: [...]|['all']}, predicate_sql (row_exclusion), positions (row_add), evidence`. Directories or files starting with `_` and names containing `.proposed.` are NOT live. `pipeline.agent_promoted.load_promoted_corrections(dir) -> list[dict]`, `load_promoted_rules(dir) -> dict[cik10, list[dict]]` accept explicit dirs. No `admission_manifest.json` exists, so every non-retired file is admitted (`allow_legacy=True`).
- `pipeline.agent_rule._match_rows(work, predicate_sql, scope) -> list[(rid, fv, report_date)]` and `match_rows_outside_scope(work, predicate_sql, scope)`; `work` must carry `_rid` and `report_date`; `_REPORT_DATE_KEY = "substr(CAST(report_date AS VARCHAR), 1, 10)"`.
- Anchors: `data/overrides/agent_anchor/{cik_stripped}/{report_date}.json` with `grand_total` (float), `method`, `components`, `evidence`.
- Rate grammars: `data/overrides/identifier_rate_grammars/{cik10}.json` with `extractors[{field, regex, group, type, map}]`, `required_fields`, `invariants`. `pipeline.identifier_rate.load_grammar(cik10) -> dict`, `apply_grammar(identifier, grammar) -> dict` (missing fields None). Grammar files exist for 70 CIKs; check existence before loading.
- `pipeline.staging_bdc._prepare_bdc(bdc_df=None, bdc_file=None, raw_exclusions=None, raw_exclusion_audits=None) -> pd.DataFrame` produces the unified-schema staged frame from a bdc_holdings-schema frame.
- `pipeline.agent_promoted.apply_promoted_plan(combined, corrections, rules_by_cik) -> (frame, audits)`.
- Tests import scripts as `from scripts.profile_pilot import ...` (namespace package; `scripts/` has no `__init__.py`, sub-packages do).
- `tests/conftest.py` autouse fixture `_isolate_promoted_agent_stores` redirects `config.AGENT_*_DIR`; loaders called with explicit dirs bypass it. `needs_cache` marker is registered in `pytest.ini`.
- Synthetic XBRL instance helpers pattern: `tests/test_context_inventory.py` (HEADER, `context()`, `typed()`, `explicit()`, `fact()`).

## File Structure

| Path | Responsibility |
|---|---|
| `scripts/profile_pilot/__init__.py` | package marker, `__version__ = "0.1"` |
| `scripts/profile_pilot/paths.py` | `PilotPaths`: resolve data root, cache/instance paths, pilot output dirs; `git_head()`, `sha256_file()` |
| `scripts/profile_pilot/cohort.py` | the eight-CIK cohort table (from spec section 5) as data; fund-quarter selection; wrapper authoring-quarter lookup |
| `scripts/profile_pilot/manifest.py` | pin reference artifacts + fund-quarter rows -> `results/manifest.json` |
| `scripts/profile_pilot/envelope.py` | entry envelope, `filer_profile_v0.schema.json` validation, overlap rule, `resolve()` as-of query |
| `scripts/profile_pilot/schemas/filer_profile_v0.schema.json` | JSON schema for a profile document |
| `scripts/profile_pilot/schemas/census_v0.schema.json` | JSON schema for a census document |
| `scripts/profile_pilot/census.py` | census of one instance: contexts (target + comparative), identifier signature, concept map, subtotal/view/status/fund-level detectors with three-state outcomes |
| `scripts/profile_pilot/profile.py` | derive profile v0 from census; M1 comparison against the hand wrapper; wrapper key inventory |
| `scripts/profile_pilot/translate.py` | profile -> wrapper v3 JSON for expressible sections (used by D2) |
| `scripts/profile_pilot/contracts.py` | learn contracts from Q1; evaluate on Q2; tolerance table; per-row grammar; fund-income yield |
| `scripts/profile_pilot/graduate.py` | correction inventory + generalisability classification (M3) |
| `scripts/profile_pilot/interpret.py` | D1 profile-driven rows from census contexts |
| `scripts/profile_pilot/parity.py` | D1 / D2 / D3 comparisons with correction replay (M4) |
| `scripts/profile_pilot/halflife.py` | all-quarter contract evaluation, censoring, KM median (M5) |
| `scripts/profile_pilot/report.py` | `results/summary.json` + investigation markdown |
| `scripts/profile_pilot/run.py` | CLI: `--data-root --cik --stage --quarters`; heavy-lock check |
| `tests/profile_pilot_xml.py` | shared synthetic-instance builder (not a test module) |
| `tests/test_profile_pilot_paths.py` ... `tests/test_profile_pilot_halflife.py` | one test file per module |
| `tests/test_profile_pilot_cache.py` | `needs_cache` tests on Stellus 2022-09-30 and NexPoint 2023-09-30 |
| `docs/investigations/filer_profile_pilot.md` | results write-up (Task 12) |

Output layout under `<data_root>/pilot/filer_profile/`:

```
results/manifest.json                 pinned inputs (Task 1)
results/wrapper_key_inventory.json    M1 denominator (Task 6)
results/correction_inventory.json     M3 denominator (Task 3)
results/contract_tolerances.json      M2 bands (Task 8)
results/graduation.json               M3 (Task 3)
census/{cik10}/{report_date}.json     Task 4/5
profiles/{cik10}.json                 Q1-derived profile (Task 6)
profiles/{cik10}.authoring.json       same-era profile (Task 6)
contracts/{cik10}.json                learned + evaluated (Task 8)
parity/{cik10}/{report_date}.json     D1/D2/D3 (Task 9)
halflife/{cik10}.json                 Task 10
results/summary.json                  Task 11
```

---

### Task 1: Package skeleton, data-root resolution, manifest pinning

**Files:**
- Create: `scripts/profile_pilot/__init__.py`
- Create: `scripts/profile_pilot/paths.py`
- Create: `scripts/profile_pilot/cohort.py`
- Create: `scripts/profile_pilot/manifest.py`
- Test: `tests/test_profile_pilot_paths.py`

**Interfaces:**
- Produces: `PilotPaths(data_root: Path)` with properties `raw_bdc_xbrl`, `output_dir`, `overrides_dir`, `pilot_dir`, `results_dir`, and methods `instance_path(cik, accession) -> Path`, `ensure_dirs()`. `resolve_data_root(explicit: str | None) -> Path`. `git_head(repo_root: Path) -> str`. `sha256_file(path) -> str`.
- Produces: `COHORT: list[dict]` with keys `cik, name, q1, q2, control, alt_control`; `fund_quarters(paths, cik, mode) -> list[dict]` returning `[{cik, report_date, form_type, accession_number, instance_path, cached: bool}]` where `mode in {"first2", "all", "authoring"}`; `authoring_quarter(paths, cik) -> str`.
- Produces: `build_manifest(paths) -> dict` and `write_manifest(paths) -> Path`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_pilot_paths.py
import json
import os
from pathlib import Path

import pytest

from scripts.profile_pilot import paths as P


def test_resolve_data_root_prefers_explicit(tmp_path, monkeypatch):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "bdc_holdings.csv").write_text("cik\n", encoding="utf-8")
    monkeypatch.delenv("PILOT_DATA_ROOT", raising=False)
    assert P.resolve_data_root(str(tmp_path)) == tmp_path


def test_resolve_data_root_rejects_root_without_holdings(tmp_path, monkeypatch):
    monkeypatch.delenv("PILOT_DATA_ROOT", raising=False)
    with pytest.raises(FileNotFoundError):
        P.resolve_data_root(str(tmp_path))


def test_instance_path_uses_stripped_cik_and_undashed_accession(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "bdc_holdings.csv").write_text("cik\n", encoding="utf-8")
    pp = P.PilotPaths(tmp_path)
    got = pp.instance_path("0001901037", "0001558370-22-016375")
    assert got == tmp_path / "raw" / "filings" / "bdc_xbrl" / "1901037" / "000155837022016375.xml"


def test_pilot_dirs_live_under_data_root_pilot(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "bdc_holdings.csv").write_text("cik\n", encoding="utf-8")
    pp = P.PilotPaths(tmp_path)
    pp.ensure_dirs()
    assert (tmp_path / "pilot" / "filer_profile" / "results").is_dir()
    assert pp.results_dir == tmp_path / "pilot" / "filer_profile" / "results"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_paths.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.profile_pilot'`

- [ ] **Step 3: Create the package and paths module**

```python
# scripts/profile_pilot/__init__.py
"""Filer-profile pilot: read-only shadow measurement (spec 2026-09-28)."""
__version__ = "0.1"
```

```python
# scripts/profile_pilot/paths.py
"""Data-root resolution and pilot output layout.

The pilot runs from a git worktree that has no data/raw or data/output. All
cache and output reads go through PilotPaths.data_root, which points at the
main checkout's data/ directory. Writes go only to <data_root>/pilot/filer_profile/.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_HOLDINGS_REL = Path("output") / "bdc_holdings.csv"


def _candidates(explicit: str | None) -> list[Path]:
    out: list[Path] = []
    if explicit:
        out.append(Path(explicit))
    env = os.environ.get("PILOT_DATA_ROOT")
    if env:
        out.append(Path(env))
    out.append(REPO_ROOT / "data")
    # worktree layout: <main>/.claude/worktrees/<name>  ->  parents[2] is <main>
    if len(REPO_ROOT.parents) >= 3:
        out.append(REPO_ROOT.parents[2] / "data")
    return out


def resolve_data_root(explicit: str | None = None) -> Path:
    """First candidate that contains output/bdc_holdings.csv; else FileNotFoundError."""
    tried = []
    for cand in _candidates(explicit):
        cand = cand.resolve()
        tried.append(str(cand))
        if (cand / _HOLDINGS_REL).is_file():
            return cand
    raise FileNotFoundError("No data root with output/bdc_holdings.csv among: " + "; ".join(tried))


def sha256_file(path: Path) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def git_head(repo_root: Path = REPO_ROOT) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root), check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


@dataclass(frozen=True)
class PilotPaths:
    data_root: Path

    @property
    def raw_bdc_xbrl(self) -> Path:
        return self.data_root / "raw" / "filings" / "bdc_xbrl"

    @property
    def output_dir(self) -> Path:
        return self.data_root / "output"

    @property
    def overrides_dir(self) -> Path:
        # Overrides are git-tracked, so the worktree copy is authoritative for this branch.
        return REPO_ROOT / "data" / "overrides"

    @property
    def pilot_dir(self) -> Path:
        return self.data_root / "pilot" / "filer_profile"

    @property
    def results_dir(self) -> Path:
        return self.pilot_dir / "results"

    def sub(self, name: str) -> Path:
        return self.pilot_dir / name

    def instance_path(self, cik: str, accession: str) -> Path:
        stripped = str(cik).lstrip("0") or "0"
        return self.raw_bdc_xbrl / stripped / (str(accession).replace("-", "") + ".xml")

    def ensure_dirs(self) -> None:
        for name in ("results", "census", "profiles", "contracts", "parity", "halflife"):
            (self.pilot_dir / name).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_profile_pilot_paths.py -q`
Expected: 4 passed

- [ ] **Step 5: Write the cohort module**

```python
# scripts/profile_pilot/cohort.py
"""Pilot cohort (spec section 5) and fund-quarter selection."""
from __future__ import annotations

import csv
import subprocess
from pathlib import Path

from scripts.profile_pilot.paths import REPO_ROOT, PilotPaths

COHORT = [
    dict(cik="0001287750", name="Ares Capital", q1="2022-09-30", q2="2022-12-31", control=False, heavy=True),
    dict(cik="0001803498", name="Blackstone Private Credit (BCRED)", q1="2022-09-30", q2="2022-12-31", control=False, heavy=True),
    dict(cik="0001901037", name="Stellus Private Credit", q1="2022-09-30", q2="2022-12-31", control=True, heavy=False),
    dict(cik="0001715933", name="TCW Direct Lending VII", q1="2023-03-31", q2="2023-06-30", control=False, heavy=False),
    dict(cik="0001920453", name="Fidelity Private Credit", q1="2023-03-31", q2="2023-06-30", control=False, heavy=False),
    dict(cik="0001860424", name="Onex Falcon Direct Lending", q1="2023-06-30", q2="2023-09-30", control=False, heavy=False),
    dict(cik="0001950803", name="Stepstone Private Credit", q1="2023-09-30", q2="2023-12-31", control=False, heavy=False),
    dict(cik="0001588272", name="NexPoint Capital", q1="2023-09-30", q2="2023-12-31", control=False, heavy=False),
]
ALT_CONTROL = dict(cik="0001377936", name="Saratoga", q1="2024-11-30")
PILOT_CIKS = tuple(c["cik"] for c in COHORT)


def cohort_entry(cik: str) -> dict:
    cik = str(cik).zfill(10)
    for c in COHORT:
        if c["cik"] == cik:
            return c
    raise KeyError(cik)


def _index_rows(paths: PilotPaths, cik: str) -> list[dict]:
    cik = str(cik).zfill(10)
    with open(paths.output_dir / "bdc_filings_index.csv", encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["cik"].zfill(10) == cik and r["form_type"] in ("10-Q", "10-K")]
    rows.sort(key=lambda r: (r["report_date"], r["filing_date"]))
    return rows


def _row_to_fq(paths: PilotPaths, r: dict) -> dict:
    p = paths.instance_path(r["cik"], r["accession_number"])
    return dict(cik=r["cik"].zfill(10), report_date=r["report_date"], form_type=r["form_type"],
                filing_date=r["filing_date"], accession_number=r["accession_number"],
                instance_path=str(p), cached=(r["xbrl_download_status"] == "cached" and p.is_file()))


def wrapper_added_date(cik: str) -> str:
    """First git commit date (YYYY-MM-DD) of the hand-authored wrapper, or '' if untracked."""
    rel = f"data/overrides/bdc_xbrl_wrappers/{str(cik).zfill(10)}.json"
    try:
        out = subprocess.run(["git", "log", "--diff-filter=A", "--date=short", "--format=%ad", "--", rel],
                             cwd=str(REPO_ROOT), check=True, capture_output=True, text=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out[-1] if out else ""


def authoring_quarter(paths: PilotPaths, cik: str) -> str:
    """Latest cached report_date whose filing_date <= wrapper add date (owner ruling 6)."""
    added = wrapper_added_date(cik)
    rows = [r for r in _index_rows(paths, cik) if r["xbrl_download_status"] == "cached"
            and (not added or r["filing_date"] <= added)]
    if not rows:
        raise LookupError(f"no cached filing at or before wrapper add date {added} for {cik}")
    return rows[-1]["report_date"]


def fund_quarters(paths: PilotPaths, cik: str, mode: str = "first2") -> list[dict]:
    """mode: first2 = spec Q1/Q2; all = every cached quarter >= Q1; authoring = the wrapper's quarter."""
    entry = cohort_entry(cik)
    rows = _index_rows(paths, cik)
    by_date = {}
    for r in rows:  # last filing per report_date wins (amendments supersede)
        by_date[r["report_date"]] = r
    if mode == "first2":
        picked = [by_date[d] for d in (entry["q1"], entry["q2"]) if d in by_date]
        if len(picked) != 2:
            raise LookupError(f"pilot quarters missing from filings index for {cik}: {entry['q1']}, {entry['q2']}")
    elif mode == "all":
        picked = [by_date[d] for d in sorted(by_date) if d >= entry["q1"]]
    elif mode == "authoring":
        picked = [by_date[authoring_quarter(paths, cik)]]
    else:
        raise ValueError(mode)
    return [_row_to_fq(paths, r) for r in picked]
```

- [ ] **Step 6: Write the manifest module**

```python
# scripts/profile_pilot/manifest.py
"""Pin every input the pilot reads: path, git HEAD, sha256, wall clock."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from scripts.profile_pilot.cohort import COHORT, fund_quarters
from scripts.profile_pilot.paths import REPO_ROOT, PilotPaths, git_head, sha256_file

REFERENCE_ARTIFACTS = ("bdc_holdings.csv", "private_markets_holdings.csv",
                       "bdc_filings_index.csv", "bdc_fund_income.csv")


def _row_counts(paths: PilotPaths, cik: str, report_date: str) -> dict:
    con = duckdb.connect()
    try:
        h = str(paths.output_dir / "bdc_holdings.csv").replace("\\", "/")
        p = str(paths.output_dir / "private_markets_holdings.csv").replace("\\", "/")
        cur, comp = con.execute(
            f"SELECT SUM(CASE WHEN period = report_date THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN period <> report_date THEN 1 ELSE 0 END) "
            f"FROM read_csv_auto('{h}', all_varchar=true) WHERE lpad(cik,10,'0') = ? AND report_date = ?",
            [cik, report_date]).fetchone()
        (uni,) = con.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{p}', all_varchar=true) "
            f"WHERE source = 'bdc' AND lpad(cik,10,'0') = ? AND report_date = ?", [cik, report_date]).fetchone()
    finally:
        con.close()
    return dict(bdc_holdings_current=int(cur or 0), bdc_holdings_comparative=int(comp or 0), unified=int(uni))


def build_manifest(paths: PilotPaths) -> dict:
    arts = {}
    for name in REFERENCE_ARTIFACTS:
        p = paths.output_dir / name
        arts[name] = dict(path=str(p), sha256=sha256_file(p), bytes=p.stat().st_size)
    fqs = []
    for c in COHORT:
        for fq in fund_quarters(paths, c["cik"], "first2"):
            fq = dict(fq)
            fq["instance_sha256"] = sha256_file(Path(fq["instance_path"])) if fq["cached"] else None
            fq.update(_row_counts(paths, c["cik"], fq["report_date"]))
            fqs.append(fq)
    return dict(pilot="filer_profile_v0", recorded_at=datetime.now(timezone.utc).isoformat(),
                git_head=git_head(REPO_ROOT), data_root=str(paths.data_root),
                reference_artifacts=arts, fund_quarters=fqs)


def write_manifest(paths: PilotPaths) -> Path:
    paths.ensure_dirs()
    out = paths.results_dir / "manifest.json"
    out.write_text(json.dumps(build_manifest(paths), indent=1), encoding="utf-8")
    return out
```

- [ ] **Step 7: Add a needs_cache smoke test and run it**

Append to `tests/test_profile_pilot_paths.py`:

```python
def _data_root_or_skip():
    try:
        return P.resolve_data_root(None)
    except FileNotFoundError:
        pytest.skip("no data root")


@pytest.mark.needs_cache
def test_manifest_pins_sixteen_cached_fund_quarters(tmp_path):
    from scripts.profile_pilot.manifest import build_manifest
    root = _data_root_or_skip()
    m = build_manifest(P.PilotPaths(root))
    assert len(m["fund_quarters"]) == 16
    assert all(fq["cached"] for fq in m["fund_quarters"]), [fq for fq in m["fund_quarters"] if not fq["cached"]]
    assert set(m["reference_artifacts"]) == {"bdc_holdings.csv", "private_markets_holdings.csv",
                                             "bdc_filings_index.csv", "bdc_fund_income.csv"}
```

Run: `python -m pytest tests/test_profile_pilot_paths.py -q`
Expected: 5 passed (the manifest test reads ~800K-row CSVs through DuckDB; allow ~1-2 minutes).

- [ ] **Step 8: Commit**

```bash
git add scripts/profile_pilot/__init__.py scripts/profile_pilot/paths.py scripts/profile_pilot/cohort.py scripts/profile_pilot/manifest.py tests/test_profile_pilot_paths.py
git commit -m "Add filer-profile pilot package skeleton and input manifest

- PilotPaths resolves the main checkout data root from the worktree
- Cohort table and fund-quarter selection incl. wrapper authoring quarter
- Manifest pins reference artifacts and 16 fund-quarters with sha256"
```

---

### Task 2: Entry envelope, profile schema v0, overlap rule, as-of resolution

**Files:**
- Create: `scripts/profile_pilot/envelope.py`
- Create: `scripts/profile_pilot/schemas/filer_profile_v0.schema.json`
- Test: `tests/test_profile_pilot_envelope.py`

**Interfaces:**
- Produces: `make_entry(key, value, *, valid_from, cik, author="census", status="derived", provenance="derived", inherited_from=None, form_type=None, applies_to=None, support=None, evidence=None, recorded_at=None, version=1) -> dict`
- Produces: `new_profile(cik, entity_name) -> dict` = `{"schema_version": "filer-profile.v0", "cik", "entity_name", "entries": []}`
- Produces: `validate_profile(profile) -> list[str]` (empty = valid; JSON-schema errors plus overlap-rule errors)
- Produces: `supersede(profile, old_entry_id, new_value, *, kind, valid_from=None, recorded_at=None) -> dict` where `kind in {"correction", "change"}`
- Produces: `resolve(profile, key, report_date, *, as_of=None, form_type=None, partition=None) -> dict | None`
- Produces: `PARTITION_KINDS = ("axis_member", "concept", "segment_count", "prefix", "grammar_dialect")`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_pilot_envelope.py
import pytest

from scripts.profile_pilot import envelope as E


def _profile_with_delim():
    p = E.new_profile("0001901037", "Stellus")
    p["entries"].append(E.make_entry("identifier_format.delimiter", ", ", valid_from="2022-09-30",
                                     cik="0001901037", support={"kind": "prevalence", "numerator": 61, "denominator": 62},
                                     recorded_at="2026-09-28T10:00:00Z"))
    return p


def test_entry_has_two_clocks_and_provenance():
    e = _profile_with_delim()["entries"][0]
    assert e["valid_from"] == "2022-09-30" and e["valid_to"] is None
    assert e["recorded_at"] == "2026-09-28T10:00:00Z" and e["recorded_until"] is None
    assert e["provenance"] == "derived" and e["inherited_from"] is None
    assert "confidence" not in e


def test_schema_rejects_unmeasured_support():
    p = _profile_with_delim()
    p["entries"][0]["support"] = {"kind": "gut_feel", "score": 0.9}
    assert any("support" in err for err in E.validate_profile(p))


def test_retrospective_correction_keeps_valid_time_and_closes_transaction_time():
    p = _profile_with_delim()
    old_id = p["entries"][0]["entry_id"]
    new = E.supersede(p, old_id, " | ", kind="correction", recorded_at="2026-10-01T00:00:00Z")
    old = next(e for e in p["entries"] if e["entry_id"] == old_id)
    assert old["recorded_until"] == "2026-10-01T00:00:00Z" and old["valid_to"] is None
    assert new["valid_from"] == "2022-09-30" and new["supersedes"] == old_id
    assert new["supersession_kind"] == "correction"
    assert E.validate_profile(p) == []


def test_genuine_change_closes_valid_time_only():
    p = _profile_with_delim()
    old_id = p["entries"][0]["entry_id"]
    new = E.supersede(p, old_id, " | ", kind="change", valid_from="2024-03-31", recorded_at="2026-10-01T00:00:00Z")
    old = next(e for e in p["entries"] if e["entry_id"] == old_id)
    assert old["valid_to"] == "2024-03-30" and old["recorded_until"] is None
    assert new["valid_from"] == "2024-03-31" and new["supersession_kind"] == "change"
    assert E.validate_profile(p) == []


def test_as_of_query_returns_old_belief_before_correction():
    p = _profile_with_delim()
    old_id = p["entries"][0]["entry_id"]
    E.supersede(p, old_id, " | ", kind="correction", recorded_at="2026-10-01T00:00:00Z")
    assert E.resolve(p, "identifier_format.delimiter", "2022-09-30", as_of="2026-09-29T00:00:00Z")["value"] == ", "
    assert E.resolve(p, "identifier_format.delimiter", "2022-09-30")["value"] == " | "


def test_overlap_rule_rejects_two_current_entries_same_key_same_partition():
    p = _profile_with_delim()
    p["entries"].append(E.make_entry("identifier_format.delimiter", " | ", valid_from="2022-09-30",
                                     cik="0001901037", recorded_at="2026-09-28T10:00:01Z", version=2))
    errs = E.validate_profile(p)
    assert any("overlap" in err for err in errs)


def test_partition_predicate_resolves_more_specific_first():
    p = _profile_with_delim()
    part = {"kind": "axis_member", "axis": "InvestmentTypeAxis", "member": "ControlledInvestmentsMember"}
    p["entries"].append(E.make_entry("identifier_format.delimiter", " | ", valid_from="2022-09-30",
                                     cik="0001901037", applies_to=part, recorded_at="2026-09-28T10:00:01Z", version=2))
    assert E.validate_profile(p) == []
    assert E.resolve(p, "identifier_format.delimiter", "2022-09-30", partition=part)["value"] == " | "
    assert E.resolve(p, "identifier_format.delimiter", "2022-09-30")["value"] == ", "


def test_row_position_is_not_a_partition_kind():
    with pytest.raises(ValueError):
        E.make_entry("k.k", 1, valid_from="2022-09-30", cik="0001901037",
                     applies_to={"kind": "row_range", "start": 0, "end": 500})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_envelope.py -q`
Expected: FAIL with `ModuleNotFoundError` on `scripts.profile_pilot.envelope`

- [ ] **Step 3: Write the JSON schema**

Save as `scripts/profile_pilot/schemas/filer_profile_v0.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "filer-profile.v0",
  "type": "object",
  "required": ["schema_version", "cik", "entity_name", "entries"],
  "properties": {
    "schema_version": {"const": "filer-profile.v0"},
    "cik": {"type": "string", "pattern": "^[0-9]{10}$"},
    "entity_name": {"type": "string"},
    "entries": {"type": "array", "items": {"$ref": "#/$defs/entry"}}
  },
  "$defs": {
    "date": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
    "stamp": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T"},
    "partition": {
      "type": "object",
      "required": ["kind"],
      "properties": {"kind": {"enum": ["axis_member", "concept", "segment_count", "prefix", "grammar_dialect"]}},
      "additionalProperties": true
    },
    "support": {
      "oneOf": [
        {"type": "object", "required": ["kind", "numerator", "denominator"],
         "properties": {"kind": {"const": "prevalence"}, "numerator": {"type": "integer"}, "denominator": {"type": "integer"}},
         "additionalProperties": false},
        {"type": "object", "required": ["kind", "count"],
         "properties": {"kind": {"const": "context_count"}, "count": {"type": "integer"}},
         "additionalProperties": false}
      ]
    },
    "entry": {
      "type": "object",
      "required": ["entry_id", "key", "value", "form_type", "applies_to", "valid_from", "valid_to",
                   "recorded_at", "recorded_until", "supersedes", "supersession_kind", "author",
                   "status", "provenance", "inherited_from", "support", "evidence", "regression_pin"],
      "properties": {
        "entry_id": {"type": "string", "minLength": 1},
        "key": {"type": "string", "pattern": "^[a-z_]+\\.[a-z_]+$"},
        "form_type": {"enum": ["10-Q", "10-K", null]},
        "applies_to": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/partition"}]},
        "valid_from": {"$ref": "#/$defs/date"},
        "valid_to": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/date"}]},
        "recorded_at": {"$ref": "#/$defs/stamp"},
        "recorded_until": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/stamp"}]},
        "supersedes": {"type": ["string", "null"]},
        "supersession_kind": {"enum": ["correction", "change", null]},
        "author": {"enum": ["census", "agent", "human"]},
        "status": {"enum": ["derived", "proposed", "verified", "promoted", "retired"]},
        "provenance": {"enum": ["derived", "inherited"]},
        "inherited_from": {"type": ["string", "null"]},
        "support": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/support"}]},
        "evidence": {"type": "array"},
        "regression_pin": {"type": ["string", "null"]}
      },
      "additionalProperties": false
    }
  }
}
```

- [ ] **Step 4: Write the envelope module**

```python
# scripts/profile_pilot/envelope.py
"""Entry envelope with two clocks (spec 6.2).

valid_from/valid_to        = report dates the filer behaviour held (valid time)
recorded_at/recorded_until = wall clock during which we believed the entry (transaction time)
Entries are immutable versions. supersede() never edits a value in place.
"""
from __future__ import annotations

import json
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "filer_profile_v0.schema.json"
PARTITION_KINDS = ("axis_member", "concept", "segment_count", "prefix", "grammar_dialect")
_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_FAR = "9999"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_profile(cik: str, entity_name: str) -> dict:
    return {"schema_version": "filer-profile.v0", "cik": str(cik).zfill(10),
            "entity_name": entity_name, "entries": []}


def make_entry(key, value, *, valid_from, cik, author="census", status="derived", provenance="derived",
               inherited_from=None, form_type=None, applies_to=None, support=None, evidence=None,
               recorded_at=None, version=1) -> dict:
    if applies_to is not None and applies_to.get("kind") not in PARTITION_KINDS:
        raise ValueError(f"applies_to.kind must be one of {PARTITION_KINDS}; row position is never a predicate")
    if provenance == "inherited" and not inherited_from:
        raise ValueError("inherited entries must name inherited_from")
    return {"entry_id": f"{str(cik).zfill(10)}:{key}:v{version}", "key": key, "value": value,
            "form_type": form_type, "applies_to": applies_to,
            "valid_from": valid_from, "valid_to": None,
            "recorded_at": recorded_at or _now(), "recorded_until": None,
            "supersedes": None, "supersession_kind": None,
            "author": author, "status": status, "provenance": provenance, "inherited_from": inherited_from,
            "support": support, "evidence": list(evidence or []), "regression_pin": None}


def _prev_day(day: str) -> str:
    y, m, d = (int(x) for x in day.split("-"))
    return (_date(y, m, d) - timedelta(days=1)).isoformat()


def supersede(profile, old_entry_id, new_value, *, kind, valid_from=None, recorded_at=None) -> dict:
    if kind not in ("correction", "change"):
        raise ValueError(kind)
    old = next(e for e in profile["entries"] if e["entry_id"] == old_entry_id)
    stamp = recorded_at or _now()
    n = 1 + max(int(e["entry_id"].rsplit(":v", 1)[1]) for e in profile["entries"] if e["key"] == old["key"])
    new = make_entry(old["key"], new_value, valid_from=old["valid_from"], cik=profile["cik"], author=old["author"],
                     status=old["status"], provenance=old["provenance"], inherited_from=old["inherited_from"],
                     form_type=old["form_type"], applies_to=old["applies_to"], support=None, evidence=[],
                     recorded_at=stamp, version=n)
    new["supersedes"] = old_entry_id
    new["supersession_kind"] = kind
    if kind == "correction":
        old["recorded_until"] = stamp          # we no longer believe the old version ...
        new["valid_to"] = old["valid_to"]      # ... but valid time does not move
    else:
        if not valid_from:
            raise ValueError("a genuine change needs the quarter it started")
        old["valid_to"] = _prev_day(valid_from)  # old stays believed, up to the day before the change
        new["valid_from"] = valid_from
    profile["entries"].append(new)
    return new


def _current(e, as_of):
    a = as_of or _FAR
    return e["recorded_at"] <= a and (e["recorded_until"] is None or e["recorded_until"] > a)


def _covers(e, report_date):
    return e["valid_from"] <= report_date and (e["valid_to"] is None or report_date <= e["valid_to"])


def _same_partition(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def resolve(profile, key, report_date, *, as_of=None, form_type=None, partition=None):
    """Order: (filer, applies_to, form_type, dated) -> (filer, form_type, dated) -> (filer, dated)."""
    cands = [e for e in profile["entries"] if e["key"] == key and _covers(e, report_date) and _current(e, as_of)]
    tiers = []
    if partition is not None:
        tiers.append([e for e in cands if _same_partition(e["applies_to"], partition) and e["form_type"] in (form_type, None)])
    if form_type is not None:
        tiers.append([e for e in cands if e["applies_to"] is None and e["form_type"] == form_type])
    tiers.append([e for e in cands if e["applies_to"] is None and e["form_type"] is None])
    for tier in tiers:
        if tier:
            return max(tier, key=lambda e: e["recorded_at"])
    return None


def validate_profile(profile) -> list[str]:
    validator = jsonschema.Draft202012Validator(_SCHEMA)
    errs = [f"schema: {err.json_path}: {err.message}" for err in
            sorted(validator.iter_errors(profile), key=lambda e: str(e.json_path))]
    live = [e for e in profile.get("entries", []) if isinstance(e, dict) and e.get("recorded_until") is None]
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if a.get("key") != b.get("key") or a.get("form_type") != b.get("form_type"):
                continue
            if not _same_partition(a.get("applies_to"), b.get("applies_to")):
                continue
            a_to, b_to = a.get("valid_to") or _FAR, b.get("valid_to") or _FAR
            if a.get("valid_from", "") <= b_to and b.get("valid_from", "") <= a_to:
                errs.append(f"overlap: {a.get('entry_id')} and {b.get('entry_id')} are both current for one key/partition")
    return errs
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_profile_pilot_envelope.py -q`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/profile_pilot/envelope.py scripts/profile_pilot/schemas/filer_profile_v0.schema.json tests/test_profile_pilot_envelope.py
git commit -m "Add filer-profile entry envelope with two clocks and partitions

- recorded_until + supersession_kind separate corrections from changes
- applies_to partition predicate; row position rejected as a kind
- Overlap validator and as-of resolve() with synthetic tests"
```

---

### Task 3: Graduation test [E] and M3 (runs first; needs no census)

**Files:**
- Create: `scripts/profile_pilot/graduate.py`
- Test: `tests/test_profile_pilot_graduate.py`

**Interfaces:**
- Consumes: `PilotPaths`, `PILOT_CIKS`, `pipeline.agent_rule._match_rows(work, predicate_sql, scope)`, `pipeline.agent_rule.match_rows_outside_scope(work, predicate_sql, scope)` (both need `_rid` and `report_date` columns), `pipeline.agent_promoted.load_promoted_corrections(dir)`, `load_promoted_rules(dir)`.
- Produces: `correction_inventory(paths, ciks) -> list[dict]` items `{cik, kind: "b2"|"rule", id, fix_class|rule_type, scope_quarters: list[str], predicate_sql|None, template: dict, live: True}`; written to `results/correction_inventory.json` BEFORE classification.
- Produces: `express(item) -> dict | None` = `{"candidate_key", "predicate_sql", "frame": "bdc_holdings"|"unified"}` or None when not expressible.
- Produces: `classify(item, frame_bdc, frame_unified, anchors) -> dict` with `class in CLASSES`, `origin_fidelity`, `touched_quarters`, `reason`, optional `anchor_verdicts`.
- Produces: `load_anchors(paths, ciks) -> dict[(cik10, report_date), float]`.
- Produces: `run_graduation(paths, ciks=PILOT_CIKS) -> dict` writing `results/graduation.json` with `denominator`, `per_class`, `per_cik`, `per_fix_class`, `results`, `M3`.

Expressibility table (spec 6.5):

| fix_class / rule_type | candidate key | predicate | frame |
|---|---|---|---|
| `comparative_period_filter` | `comparative_periods.rule` | `period <> report_date` | bdc_holdings |
| `row_exclusion` with `predicate_sql` | `presentation_views.exclusion` if the predicate mentions `axis`, else `subtotals_and_headings.exclusion` | the rule's `predicate_sql` | unified |
| `subtotal_filter` with `template.pattern` | `subtotals_and_headings.marker` | `regexp_matches(lower(investment_identifier), '<pattern>')` | bdc_holdings |
| all others (`column_remap`, `classification_fix`, `all_pik_normalization`, `unit_rescale`, `missing_position_add`, `dedup`, `row_add`, `value_rescale`, `value_expression`) | none | none | `not_expressible` |

- [ ] **Step 1: Write the failing tests (synthetic frames)**

```python
# tests/test_profile_pilot_graduate.py
import pandas as pd
import pytest

from scripts.profile_pilot import graduate as G


def _bdc_frame():
    rows = []
    for q in ("2023-03-31", "2023-06-30", "2023-09-30"):
        rows += [dict(cik="0001715933", report_date=q, period=q, investment_identifier=f"Acme {q}", fair_value=100.0),
                 dict(cik="0001715933", report_date=q, period="2022-12-31", investment_identifier="Acme prior", fair_value=90.0)]
    df = pd.DataFrame(rows)
    df["_rid"] = range(len(df))
    return df


def _unified_frame():
    rows = []
    for q in ("2023-03-31", "2023-06-30", "2023-09-30"):
        rows += [dict(cik="0001715933", report_date=q, issuer_name="Acme", fair_value=100.0,
                      bdc_dimensions_raw="investmentidentifieraxis=Acme"),
                 dict(cik="0001715933", report_date=q, issuer_name="Acme", fair_value=100.0,
                      bdc_dimensions_raw="investmentidentifieraxis=Controlled Investments Acme")]
    df = pd.DataFrame(rows)
    df["_rid"] = range(len(df))
    return df


def _rule(predicate):
    return dict(cik="0001715933", kind="rule", id="r1", rule_type="row_exclusion", scope_quarters=["2023-03-31"],
                predicate_sql=predicate, template={}, live=True)


CONTROLLED = "bdc_dimensions_raw LIKE 'investmentidentifieraxis=Controlled Investments%'"


def test_comparative_filter_generalises_with_anchor_support():
    item = dict(cik="0001715933", kind="b2", id="comparative_period_filter", fix_class="comparative_period_filter",
                scope_quarters=["2023-03-31"], template={}, live=True)
    anchors = {("0001715933", "2023-06-30"): 100.0, ("0001715933", "2023-09-30"): 100.0}
    res = G.classify(item, _bdc_frame(), _unified_frame(), anchors)
    assert res["origin_fidelity"] is True
    assert res["class"] == "generalises"
    assert res["touched_quarters"] == ["2023-06-30", "2023-09-30"]


def test_exclusion_without_anchor_is_insufficient_evidence():
    res = G.classify(_rule(CONTROLLED), _bdc_frame(), _unified_frame(), anchors={})
    assert res["class"] == "insufficient_evidence"


def test_exclusion_that_moves_total_away_from_anchor_conflicts():
    anchors = {("0001715933", "2023-06-30"): 200.0, ("0001715933", "2023-09-30"): 200.0}
    res = G.classify(_rule(CONTROLLED), _bdc_frame(), _unified_frame(), anchors)
    assert res["class"] == "conflicts"


def test_exclusion_that_lands_on_anchor_generalises():
    anchors = {("0001715933", "2023-06-30"): 100.0, ("0001715933", "2023-09-30"): 100.0}
    res = G.classify(_rule(CONTROLLED), _bdc_frame(), _unified_frame(), anchors)
    assert res["class"] == "generalises"


def test_row_id_pinned_value_fix_is_not_expressible():
    item = dict(cik="0001287750", kind="b2", id="all_pik_normalization", fix_class="all_pik_normalization",
                scope_quarters=["2025-12-31"], template={"row_selector": {"row_id": "ROW-1"}}, live=True)
    assert G.express(item) is None
    assert G.classify(item, _bdc_frame(), _unified_frame(), {})["class"] == "not_expressible"


def test_fidelity_failure_is_not_expressible():
    res = G.classify(_rule("issuer_name = 'Nobody'"), _bdc_frame(), _unified_frame(), {})
    assert res["origin_fidelity"] is False and res["class"] == "not_expressible"


def test_all_quarter_rule_is_quarter_bound_nothing_to_carry():
    item = _rule(CONTROLLED)
    item["scope_quarters"] = ["all"]
    assert G.classify(item, _bdc_frame(), _unified_frame(), {})["class"] == "insufficient_evidence"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_graduate.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the graduation module**

```python
# scripts/profile_pilot/graduate.py
"""Graduation test [E]: which live corrections generalise into dated profile entries (spec 6.5)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb
import pandas as pd

from pipeline.agent_promoted import load_promoted_corrections, load_promoted_rules
from pipeline.agent_rule import _match_rows, match_rows_outside_scope
from scripts.profile_pilot.cohort import PILOT_CIKS
from scripts.profile_pilot.paths import REPO_ROOT, PilotPaths, git_head

CLASSES = ("generalises", "quarter_bound", "conflicts", "insufficient_evidence", "not_expressible")
ANCHOR_BAND = 0.01  # within 1% of the anchor total counts as reconciled


def _cik10(x) -> str:
    return str(x).zfill(10)


def correction_inventory(paths: PilotPaths, ciks=PILOT_CIKS) -> list[dict]:
    want = {_cik10(c) for c in ciks}
    out = []
    for leaf in load_promoted_corrections(paths.overrides_dir / "agent_b2_corrections"):
        if _cik10(leaf.get("cik")) not in want:
            continue
        tmpl = leaf.get("template") or {}
        scope = (leaf.get("scope") or {}).get("quarters") or ([tmpl["report_date"]] if "report_date" in tmpl else ["all"])
        out.append(dict(cik=_cik10(leaf["cik"]), kind="b2", id=leaf.get("fix_class"), fix_class=leaf.get("fix_class"),
                        scope_quarters=[str(q) for q in scope], predicate_sql=None, template=tmpl, live=True))
    for cik10, rules in load_promoted_rules(paths.overrides_dir / "agent_investigate_rules").items():
        if _cik10(cik10) not in want:
            continue
        for r in rules:
            out.append(dict(cik=_cik10(cik10), kind="rule", id=r.get("rule_id"), rule_type=r.get("rule_type"),
                            scope_quarters=[str(q) for q in (r.get("scope") or {}).get("quarters") or ["all"]],
                            predicate_sql=r.get("predicate_sql"), template={}, live=True))
    return out


def express(item: dict) -> dict | None:
    fc = item.get("fix_class") or item.get("rule_type")
    if fc == "comparative_period_filter":
        return dict(candidate_key="comparative_periods.rule", predicate_sql="period <> report_date", frame="bdc_holdings")
    if fc == "row_exclusion" and item.get("predicate_sql"):
        key = "presentation_views.exclusion" if "axis" in item["predicate_sql"].lower() else "subtotals_and_headings.exclusion"
        return dict(candidate_key=key, predicate_sql=item["predicate_sql"], frame="unified")
    if fc == "subtotal_filter" and (item.get("template") or {}).get("pattern"):
        pat = str(item["template"]["pattern"]).replace("'", "''")
        return dict(candidate_key="subtotals_and_headings.marker",
                    predicate_sql=f"regexp_matches(lower(investment_identifier), '{pat}')", frame="bdc_holdings")
    return None


def _fv_total(frame: pd.DataFrame, quarter: str) -> float:
    con = duckdb.connect()
    try:
        con.register("h", frame)
        (v,) = con.execute("SELECT COALESCE(SUM(TRY_CAST(fair_value AS DOUBLE)), 0) FROM h "
                           "WHERE substr(CAST(report_date AS VARCHAR), 1, 10) = ?", [quarter]).fetchone()
    finally:
        con.close()
    return float(v or 0.0)


def _current_fv(frame: pd.DataFrame, quarter: str) -> float:
    cur = frame[(frame["report_date"].astype(str).str[:10] == quarter) & (frame["period"].astype(str).str[:10] == quarter)]
    return float(pd.to_numeric(cur["fair_value"], errors="coerce").fillna(0).sum())


def classify(item: dict, frame_bdc: pd.DataFrame, frame_unified: pd.DataFrame, anchors: dict) -> dict:
    """anchors: {(cik10, report_date): grand_total}."""
    base = dict(id=item["id"], cik=item["cik"], kind=item["kind"], fix_class=item.get("fix_class") or item.get("rule_type"),
                origin_fidelity=None, touched_quarters=[], reason="")
    ex = express(item)
    if ex is None:
        return {**base, "class": "not_expressible", "reason": "row_id-pinned or value fix; no structural candidate"}
    frame = frame_bdc if ex["frame"] == "bdc_holdings" else frame_unified
    frame = frame[frame["cik"].astype(str).str.zfill(10) == item["cik"]]
    if frame.empty:
        return {**base, "class": "insufficient_evidence", "reason": "no rows for filer in frame"}
    scope = {"quarters": item["scope_quarters"]}
    if "all" in item["scope_quarters"]:
        base["origin_fidelity"] = len(_match_rows(frame, ex["predicate_sql"], scope)) > 0
        return {**base, "class": "insufficient_evidence", "reason": "already scoped to all quarters; nothing to carry forward"}
    fidelity = len(_match_rows(frame, ex["predicate_sql"], scope)) > 0
    base["origin_fidelity"] = fidelity
    if not fidelity:
        return {**base, "class": "not_expressible", "reason": "candidate selects no rows on its own quarter"}
    touched: dict[str, dict] = {}
    for _rid, fv, rd in match_rows_outside_scope(frame, ex["predicate_sql"], scope):
        t = touched.setdefault(str(rd)[:10], dict(rows=0, fv=0.0))
        t["rows"] += 1
        t["fv"] += float(fv or 0.0)
    base["touched_quarters"] = sorted(touched)
    if not touched:
        return {**base, "class": "quarter_bound", "reason": "touches nothing outside its quarter"}
    if len(touched) < 2:
        return {**base, "class": "insufficient_evidence", "reason": "touches only one other quarter"}
    verdicts = {}
    for q in sorted(touched):
        anchor = anchors.get((item["cik"], q))
        if not anchor:
            verdicts[q] = "insufficient_evidence"
            continue
        if ex["candidate_key"] == "comparative_periods.rule":
            before, after = _fv_total(frame, q), _current_fv(frame, q)
        else:
            before = _fv_total(frame, q)
            after = before - touched[q]["fv"]
        err_before, err_after = abs(before - anchor) / anchor, abs(after - anchor) / anchor
        verdicts[q] = "supports" if (err_after <= ANCHOR_BAND or err_after < err_before) else "conflicts"
    vals = list(verdicts.values())
    if "conflicts" in vals:
        cls, reason = "conflicts", "excluding the touched rows moves at least one quarter away from its anchor"
    elif vals.count("supports") >= 2:
        cls, reason = "generalises", "same row class recurs and anchored totals move toward the filer figure"
    else:
        cls, reason = "insufficient_evidence", "fewer than two anchored quarters support the candidate"
    return {**base, "class": cls, "reason": reason, "anchor_verdicts": verdicts}


def load_anchors(paths: PilotPaths, ciks=PILOT_CIKS) -> dict:
    out = {}
    for c in ciks:
        d = paths.overrides_dir / "agent_anchor" / (str(c).lstrip("0") or "0")
        for p in sorted(d.glob("*.json")) if d.exists() else []:
            try:
                gt = json.loads(p.read_text(encoding="utf-8-sig")).get("grand_total")
            except (OSError, json.JSONDecodeError):
                continue
            if gt:
                out[(_cik10(c), p.stem)] = float(gt)
    return out


def _load_frames(paths: PilotPaths, ciks):
    ciks_sql = ",".join(f"'{_cik10(c)}'" for c in ciks)
    h = str(paths.output_dir / "bdc_holdings.csv").replace("\\", "/")
    u = str(paths.output_dir / "private_markets_holdings.csv").replace("\\", "/")
    con = duckdb.connect()
    try:
        bdc = con.execute(
            f"SELECT lpad(cik,10,'0') AS cik, report_date, period, investment_identifier, fair_value, "
            f"row_number() OVER () AS _rid FROM read_csv_auto('{h}', all_varchar=true) "
            f"WHERE lpad(cik,10,'0') IN ({ciks_sql})").df()
        uni = con.execute(
            f"SELECT lpad(cik,10,'0') AS cik, report_date, issuer_name, bdc_investment_identifier, "
            f"bdc_dimensions_raw, fair_value, row_id, row_number() OVER () AS _rid "
            f"FROM read_csv_auto('{u}', all_varchar=true) WHERE source = 'bdc' AND lpad(cik,10,'0') IN ({ciks_sql})").df()
    finally:
        con.close()
    return bdc, uni


def run_graduation(paths: PilotPaths, ciks=PILOT_CIKS) -> dict:
    paths.ensure_dirs()
    stamp = datetime.now(timezone.utc).isoformat()
    inventory = correction_inventory(paths, ciks)
    (paths.results_dir / "correction_inventory.json").write_text(
        json.dumps(dict(recorded_at=stamp, git_head=git_head(REPO_ROOT), items=inventory), indent=1), encoding="utf-8")
    bdc, uni = _load_frames(paths, ciks)
    anchors = load_anchors(paths, ciks)
    results = [classify(it, bdc, uni, anchors) for it in inventory]
    denom = len(inventory)
    per_class = {c: sum(1 for r in results if r["class"] == c) for c in CLASSES}
    per_cik = {c: {k: sum(1 for r in results if r["cik"] == c and r["class"] == k) for k in CLASSES}
               for c in sorted({r["cik"] for r in results})}
    per_fix: dict[str, dict] = {}
    for r in results:
        per_fix.setdefault(str(r["fix_class"]), {k: 0 for k in CLASSES})[r["class"]] += 1
    out = dict(recorded_at=stamp, git_head=git_head(REPO_ROOT), denominator=denom, per_class=per_class,
               per_cik=per_cik, per_fix_class=per_fix, results=results,
               M3=dict(generalises=per_class["generalises"], denominator=denom,
                       yield_pct=(round(100.0 * per_class["generalises"] / denom, 1) if denom else None)))
    (paths.results_dir / "graduation.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out
```

- [ ] **Step 4: Run the synthetic tests to verify they pass**

Run: `python -m pytest tests/test_profile_pilot_graduate.py -q`
Expected: 7 passed

- [ ] **Step 5: Add the cache-backed run and execute it (light job, reads two large CSVs once)**

Append to the test file:

```python
@pytest.mark.needs_cache
def test_run_graduation_on_pilot_cohort_writes_fixed_denominator():
    from scripts.profile_pilot.paths import PilotPaths, resolve_data_root
    try:
        root = resolve_data_root(None)
    except FileNotFoundError:
        pytest.skip("no data root")
    out = G.run_graduation(PilotPaths(root))
    assert out["denominator"] == len(out["results"]) > 0
    assert sum(out["per_class"].values()) == out["denominator"]
    assert (root / "pilot" / "filer_profile" / "results" / "correction_inventory.json").is_file()
```

Run: `python -m pytest tests/test_profile_pilot_graduate.py -q -k cohort`
Expected: 1 passed within a few minutes. Expected inventory size is about 23 items (Ares 3 B2 + 3 rules, BCRED 6 rules, TCW 4 rules, Fidelity 1 B2 + 2 rules, Onex 1 rule, Stepstone 1 B2 + 2 rules, per the 2026-09-28 file count). Record the actual denominator and per-class counts in the commit body. This is M3.

- [ ] **Step 6: Commit**

```bash
git add scripts/profile_pilot/graduate.py tests/test_profile_pilot_graduate.py
git commit -m "Add graduation test for pilot corrections (M3)

- Inventory of live B2 leaves and investigate rules pinned before classification
- Origin-quarter fidelity, then anchor-backed check on touched quarters
- insufficient_evidence is a first-class outcome; denominator = <N> items"
```

---

### Task 4: Census collectors with three-state detectors (synthetic instances)

**Files:**
- Create: `tests/profile_pilot_xml.py` (shared synthetic-instance builder; not a test module)
- Create: `scripts/profile_pilot/census.py`
- Create: `scripts/profile_pilot/schemas/census_v0.schema.json`
- Test: `tests/test_profile_pilot_census.py`

**Interfaces:**
- Consumes: `pipeline.context_inventory.scan_instance`, `pipeline.explicit_contexts.rule_for`.
- Produces: `census_instance(path: Path, cik: str, report_date: str, *, form_type: str = "", accession: str = "", max_comparative_scans: int = 3, timeout_seconds: float = 120.0) -> dict` with keys:
  `schema_version="census.v0", cik, report_date, form_type, accession, path, sha256, recorded_at, elapsed_s, inherited: list[str], counts: {positions, aggregates, unresolved, comparative_contexts}, identifier_signature: {axis, delimiters: [{delimiter, prevalence: {numerator, denominator}}], segment_counts: {"2": n, ...}, prefix_vocabulary: [{prefix, count}], ordinal_suffix_share}, concept_map: {field: {concept: {count, standard: bool}}}, fill_rates: {field: {numerator, denominator}}, subtotal_candidates: [{context_id, identifier, fair_value, child_count, outcome, reason}], presentation_views: [{context_ids, identifiers, axis_sets, outcome, reason}], comparative_periods: {periods: [..], contexts: n, distinguished_by: "context_period", paired_identifier_share: {numerator, denominator}}, status_markers: {nonaccrual: {location, outcome, examples}, pik: {...}, pledged: {...}}, non_disclosure: {field: {outcome, reason}}, fund_level: {concepts: [..], total_investments_fv: float|None}, position_identity: {axis, kind, outcome, provenance, inherited_from}`.
- Produces: `write_census(paths, census) -> Path` at `census/{cik10}/{report_date}.json`.
- Produces: `DETECTOR_OUTCOMES = ("resolved", "candidate", "insufficient_evidence")`.
- Produces (tests helper): `build_instance(contexts: list[dict], *, cik="1901037") -> str` where each context dict is `{id, date, dims: [(axis, member_or_text, "typed"|"explicit")], facts: {concept_qname: value}}`.

- [ ] **Step 1: Write the shared synthetic builder**

```python
# tests/profile_pilot_xml.py
"""Synthetic XBRL instance builder for filer-profile pilot tests (mirrors tests/test_context_inventory.py)."""
from xml.sax.saxutils import escape

HEADER = '''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:iso="http://www.xbrl.org/2003/iso4217"
 xmlns:gaap="http://fasb.org/us-gaap/2022" xmlns:dei="http://xbrl.sec.gov/dei/2022"
 xmlns:f="http://example.test/fund">
 <xbrli:unit id="USD"><xbrli:measure>iso:USD</xbrli:measure></xbrli:unit>
 <xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>'''
IDENT_AXIS = "f:InvestmentIdentifierAxis"
FV = "gaap:InvestmentOwnedAtFairValue"
COST = "gaap:InvestmentOwnedAtCost"
PRINCIPAL = "gaap:InvestmentOwnedBalancePrincipalAmount"
RATE = "gaap:InvestmentInterestRate"


def _dim(axis, value, kind):
    if kind == "typed":
        return (f'<xbrldi:typedMember dimension="{axis}"><f:Identifier>{escape(value)}</f:Identifier>'
                '</xbrldi:typedMember>')
    return f'<xbrldi:explicitMember dimension="{axis}">{value}</xbrldi:explicitMember>'


def build_instance(contexts, *, cik="1901037"):
    ctx_xml, fact_xml = [], []
    for c in contexts:
        dims = "".join(_dim(a, v, k) for a, v, k in c.get("dims", []))
        seg = f"<xbrli:segment>{dims}</xbrli:segment>" if dims else ""
        ctx_xml.append(f'''<xbrli:context id="{c["id"]}"><xbrli:entity>
 <xbrli:identifier scheme="http://www.sec.gov/CIK">{cik}</xbrli:identifier>{seg}</xbrli:entity>
 <xbrli:period><xbrli:instant>{c["date"]}</xbrli:instant></xbrli:period></xbrli:context>''')
        for concept, value in c.get("facts", {}).items():
            unit = "pure" if "Rate" in concept else "USD"
            fact_xml.append(f'<{concept} contextRef="{c["id"]}" unitRef="{unit}" decimals="0">{value}</{concept}>')
    return HEADER + "".join(ctx_xml) + "".join(fact_xml) + "</xbrli:xbrl>"


def position(cid, ident, fv, *, date="2022-09-30", cost=None, principal=None, rate=None, extra_dims=()):
    facts = {FV: fv}
    if cost is not None:
        facts[COST] = cost
    if principal is not None:
        facts[PRINCIPAL] = principal
    if rate is not None:
        facts[RATE] = rate
    return dict(id=cid, date=date, dims=[(IDENT_AXIS, ident, "typed"), *extra_dims], facts=facts)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_profile_pilot_census.py
from pathlib import Path

import pytest

from scripts.profile_pilot import census as C
from tests.profile_pilot_xml import FV, IDENT_AXIS, build_instance, position


def _write(tmp_path, xml):
    p = tmp_path / "inst.xml"
    p.write_text(xml, encoding="utf-8")
    return p


def _base_positions():
    return [
        position("c1", "Acme Corp | First Lien Term Loan | 9.50% | 2027-06-30", 100, cost=98, principal=101, rate=0.095),
        position("c2", "Beta LLC | Second Lien Term Loan | 11.00% | 2028-01-31", 50, cost=49, principal=50, rate=0.11),
        position("c3", "Gamma Inc | Common Equity", 25, cost=20),
    ]


def test_delimiter_prevalence_and_segment_counts(tmp_path):
    p = _write(tmp_path, build_instance(_base_positions()))
    cen = C.census_instance(p, "1901037", "2022-09-30")
    top = cen["identifier_signature"]["delimiters"][0]
    assert top["delimiter"] == " | " and top["prevalence"] == {"numerator": 3, "denominator": 3}
    assert cen["identifier_signature"]["segment_counts"] == {"4": 2, "2": 1}
    assert cen["counts"]["positions"] == 3


def test_labelled_sum_context_is_resolved_subtotal(tmp_path):
    ctxs = _base_positions() + [position("t1", "Total First and Second Lien", 150)]
    cen = C.census_instance(_write(tmp_path, build_instance(ctxs)), "1901037", "2022-09-30")
    t = next(s for s in cen["subtotal_candidates"] if s["context_id"] == "t1")
    assert t["outcome"] == "resolved" and t["child_count"] == 2


def test_unlabelled_coincidental_sum_stays_candidate(tmp_path):
    ctxs = _base_positions() + [position("c4", "Delta Holdings | Unitranche | 8.00% | 2029-12-31", 150)]
    cen = C.census_instance(_write(tmp_path, build_instance(ctxs)), "1901037", "2022-09-30")
    d = next(s for s in cen["subtotal_candidates"] if s["context_id"] == "c4")
    assert d["outcome"] == "candidate"


def test_identical_values_same_identifier_other_axis_is_resolved_view(tmp_path):
    ctxs = _base_positions() + [position("v1", "Acme Corp | First Lien Term Loan | 9.50% | 2027-06-30", 100, cost=98,
                                          principal=101, extra_dims=[("f:AffiliationAxis", "f:ControlledMember", "explicit")])]
    cen = C.census_instance(_write(tmp_path, build_instance(ctxs)), "1901037", "2022-09-30")
    v = cen["presentation_views"][0]
    assert sorted(v["context_ids"]) == ["c1", "v1"] and v["outcome"] == "resolved"


def test_identical_values_different_identifiers_is_candidate_not_duplicate(tmp_path):
    ctxs = _base_positions() + [position("v2", "Zeta Corp | First Lien Term Loan | 9.50% | 2027-06-30", 100, cost=98,
                                          principal=101, extra_dims=[("f:AffiliationAxis", "f:ControlledMember", "explicit")])]
    cen = C.census_instance(_write(tmp_path, build_instance(ctxs)), "1901037", "2022-09-30")
    v = cen["presentation_views"][0]
    assert v["outcome"] == "candidate"


def test_comparative_contexts_counted_and_paired(tmp_path):
    ctxs = _base_positions() + [position("p1", "Acme Corp | First Lien Term Loan | 9.50% | 2027-06-30", 90, date="2021-12-31")]
    cen = C.census_instance(_write(tmp_path, build_instance(ctxs)), "1901037", "2022-09-30")
    cp = cen["comparative_periods"]
    assert cp["periods"] == ["2021-12-31"] and cp["contexts"] == 1
    assert cp["paired_identifier_share"] == {"numerator": 1, "denominator": 1}


def test_missing_rate_concept_with_rate_in_text_is_insufficient_evidence(tmp_path):
    ctxs = [position("c1", "Acme Corp | First Lien | 9.50% | 2027-06-30", 100)]
    cen = C.census_instance(_write(tmp_path, build_instance(ctxs)), "1901037", "2022-09-30")
    assert cen["non_disclosure"]["interest_rate"]["outcome"] == "insufficient_evidence"


def test_missing_maturity_with_no_text_hint_is_derived_non_disclosure(tmp_path):
    ctxs = [position("c1", "Acme Corp | Common Equity", 100), position("c2", "Beta LLC | Preferred Equity", 40)]
    cen = C.census_instance(_write(tmp_path, build_instance(ctxs)), "1901037", "2022-09-30")
    assert cen["non_disclosure"]["maturity_date"]["outcome"] == "resolved"


def test_position_identity_is_typed_identifier_axis_and_not_inherited_for_typed_filer(tmp_path):
    cen = C.census_instance(_write(tmp_path, build_instance(_base_positions())), "1901037", "2022-09-30")
    pi = cen["position_identity"]
    assert pi["kind"] == "typed" and pi["axis"].endswith("InvestmentIdentifierAxis")
    assert pi["provenance"] == "derived"
    assert "pipeline.explicit_contexts" not in cen["inherited"]


def test_census_validates_against_schema(tmp_path):
    cen = C.census_instance(_write(tmp_path, build_instance(_base_positions())), "1901037", "2022-09-30")
    assert C.validate_census(cen) == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_census.py -q`
Expected: FAIL with `ModuleNotFoundError` on `scripts.profile_pilot.census`

- [ ] **Step 4: Write the census module**

```python
# scripts/profile_pilot/census.py
"""Deterministic structural census of one cached XBRL instance (spec 6.1).

Every detector returns resolved / candidate / insufficient_evidence, never a bare assertion.
Context classification is reused from pipeline.context_inventory and is INHERITED where the
filer has an explicit-member identity rule in pipeline.explicit_contexts.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from pipeline.context_inventory import scan_instance
from pipeline.explicit_contexts import rule_for
from scripts.profile_pilot.paths import PilotPaths, sha256_file

DETECTOR_OUTCOMES = ("resolved", "candidate", "insufficient_evidence")
CANONICAL_FIELDS = ("fair_value", "cost", "principal", "interest_rate", "basis_spread", "pik_rate",
                    "maturity", "shares", "industry", "affiliation", "nonaccrual")
DELIMITERS = (" | ", ", ", " - ", "; ", " / ")
_TOTAL_RE = re.compile(r"\b(sub)?total\b", re.I)
_RATE_TEXT_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\b(?:SOFR|LIBOR|PRIME|EURIBOR)\b", re.I)
_DATE_TEXT_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b")
_ORDINAL_RE = re.compile(r"\s\d{1,3}$")
_STANDARD_NS_RE = re.compile(r"https?://(?:fasb\.org/us-gaap|xbrl\.sec\.gov/dei)/")
_TEXT_HINT = {"interest_rate": _RATE_TEXT_RE, "basis_spread": _RATE_TEXT_RE, "pik_rate": re.compile(r"\bPIK\b", re.I),
              "maturity": _DATE_TEXT_RE}
_STATUS_KEYWORDS = {"nonaccrual": ("nonaccrual", "non-accrual", "non accrual"),
                    "pik": ("paidinkind", "paid-in-kind", "pik"),
                    "pledged": ("pledged", "collateral")}
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "census_v0.schema.json"


def _local(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _identifier(ctx: dict) -> str | None:
    typed = [d for d in ctx["dimensions"] if d["kind"] == "typed"]
    if not typed:
        return None
    pref = [d for d in typed if "identifier" in _local(d["axis"]).lower()]
    return (pref or typed)[0]["value"]


def _fact_value(ctx: dict, field: str):
    for f in ctx["facts"]:
        if f["field"] == field and f["value"] is not None:
            return float(f["value"])
    return None


def _dim_set(ctx: dict) -> frozenset:
    return frozenset((d["axis"], d["value"]) for d in ctx["dimensions"])


def _prevalence(n: int, d: int) -> dict:
    return {"numerator": int(n), "denominator": int(d)}


def _identifier_signature(positions: list[dict], axis: str | None) -> dict:
    idents = [i for i in (_identifier(c) for c in positions) if i]
    n = len(idents)
    delims = []
    for d in DELIMITERS:
        k = sum(1 for i in idents if d in i)
        if k:
            delims.append({"delimiter": d, "prevalence": _prevalence(k, n)})
    delims.sort(key=lambda x: -x["prevalence"]["numerator"])
    top = delims[0]["delimiter"] if delims else None
    seg_counts = Counter(str(len(i.split(top))) if top else "1" for i in idents)
    prefixes = Counter(i.split(top)[0].strip() for i in idents) if top else Counter()
    vocab = [{"prefix": p, "count": c} for p, c in prefixes.most_common() if c >= 3]
    ordinal = sum(1 for i in idents if _ORDINAL_RE.search(i))
    return {"axis": axis, "delimiters": delims, "segment_counts": dict(sorted(seg_counts.items())),
            "prefix_vocabulary": vocab, "ordinal_suffix_share": _prevalence(ordinal, n)}


def _concept_map(positions: list[dict]) -> tuple[dict, dict]:
    cmap: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    have: dict[str, int] = defaultdict(int)
    for c in positions:
        seen = set()
        for f in c["facts"]:
            if not f["field"]:
                continue
            ns = f["concept"][1:].split("}", 1)[0] if str(f["concept"]).startswith("{") else ""
            cmap[f["field"]][f["concept"]] += 1
            cmap[f["field"]][f["concept"] + "::standard"] = bool(_STANDARD_NS_RE.match(ns))
            seen.add(f["field"])
        for fld in seen:
            have[fld] += 1
    out = {}
    for fld, d in cmap.items():
        out[fld] = {k: {"count": v, "standard": bool(d.get(k + "::standard", False))}
                    for k, v in d.items() if not k.endswith("::standard")}
    fills = {fld: _prevalence(have[fld], len(positions)) for fld in CANONICAL_FIELDS}
    return out, fills


def _subtotals(all_ctx: list[dict], positions: list[dict]) -> list[dict]:
    out = []
    pos_ids = {c["context_id"] for c in positions}
    for parent in all_ctx:
        pfv = _fact_value(parent, "fair_value")
        if pfv is None:
            continue
        pdims = _dim_set(parent)
        kids = [c for c in positions if c["context_id"] != parent["context_id"] and c["period"] == parent["period"]
                and _dim_set(c) > pdims and _fact_value(c, "fair_value") is not None]
        if len(kids) < 2:
            # a typed identifier is a leaf, not a group: try siblings on the same axis set whose FV sums to it
            kids = [c for c in positions if c["context_id"] != parent["context_id"] and c["period"] == parent["period"]
                    and len(c["dimensions"]) == len(parent["dimensions"]) and _fact_value(c, "fair_value") is not None]
            total = sum(_fact_value(c, "fair_value") for c in kids)
            if not kids or abs(total - pfv) > 1.0:
                # fall back to any 2+ subset summing to the value is too permissive; require exact full-sibling sum
                kids = _subset_sum(kids, pfv)
        total = sum(_fact_value(c, "fair_value") for c in kids) if kids else None
        if not kids or len(kids) < 2 or total is None or abs(total - pfv) > 1.0:
            continue
        ident = _identifier(parent) or ""
        labelled = bool(_TOTAL_RE.search(ident)) or not parent["dimensions"]
        out.append({"context_id": parent["context_id"], "identifier": ident, "fair_value": pfv,
                    "child_count": len(kids), "child_context_ids": sorted(c["context_id"] for c in kids),
                    "outcome": "resolved" if labelled else "candidate",
                    "reason": "label reads as a total" if labelled else "sum equality only; label does not read as a total"})
    return out


def _subset_sum(cands: list[dict], target: float, limit: int = 12) -> list[dict]:
    """Exact-sum search over at most `limit` sibling contexts (bounded, deterministic)."""
    cands = sorted(cands, key=lambda c: -(_fact_value(c, "fair_value") or 0))[:limit]
    vals = [_fact_value(c, "fair_value") for c in cands]
    n = len(vals)
    for mask in range(3, 1 << n):
        if bin(mask).count("1") < 2:
            continue
        if abs(sum(v for i, v in enumerate(vals) if mask >> i & 1) - target) <= 1.0:
            return [c for i, c in enumerate(cands) if mask >> i & 1]
    return []


def _views(positions: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for c in positions:
        key = (c["period"], _fact_value(c, "fair_value"), _fact_value(c, "cost"), _fact_value(c, "principal"))
        if key[1] is None:
            continue
        groups[key].append(c)
    out = []
    for key, ctxs in groups.items():
        axis_sets = {frozenset(d["axis"] for d in c["dimensions"]) for c in ctxs}
        if len(ctxs) < 2 or len(axis_sets) < 2:
            continue
        idents = {" ".join((_identifier(c) or "").lower().split()) for c in ctxs}
        same = len(idents) == 1 and "" not in idents
        out.append({"context_ids": sorted(c["context_id"] for c in ctxs), "identifiers": sorted(idents),
                    "axis_sets": sorted(sorted(_local(a) for a in s) for s in axis_sets),
                    "outcome": "resolved" if same else "candidate",
                    "reason": "identical values and identical identifier under different axes" if same
                    else "identical values only; identifiers differ, tranches may coincide"})
    return out


def _status_markers(all_ctx: list[dict]) -> dict:
    out = {}
    for name, kws in _STATUS_KEYWORDS.items():
        dim_hits, concept_hits = [], []
        for c in all_ctx:
            for d in c["dimensions"]:
                v = (d["value"] + " " + _local(d["axis"])).lower().replace("_", "")
                if any(k.replace("-", "").replace(" ", "") in v.replace("-", "").replace(" ", "") for k in kws):
                    dim_hits.append(d["value"])
            for f in c["facts"]:
                v = _local(f["concept"]).lower()
                if any(k.replace("-", "").replace(" ", "") in v for k in kws):
                    concept_hits.append(_local(f["concept"]))
        if dim_hits:
            out[name] = {"location": "dimension_member", "outcome": "resolved", "examples": sorted(set(dim_hits))[:5]}
        elif concept_hits:
            out[name] = {"location": "concept", "outcome": "resolved", "examples": sorted(set(concept_hits))[:5]}
        else:
            out[name] = {"location": "absent_in_instance", "outcome": "insufficient_evidence",
                         "examples": [], "reason": "may live in footnote text the instance census cannot see"}
    return out


def _non_disclosure(positions: list[dict], fills: dict) -> dict:
    texts = " || ".join(i for i in (_identifier(c) for c in positions) if i)
    out = {}
    for fld in ("interest_rate", "basis_spread", "pik_rate", "maturity", "principal", "cost"):
        if fills.get(fld, {}).get("numerator", 0) > 0:
            continue
        hint = _TEXT_HINT.get(fld)
        if hint is not None and hint.search(texts):
            out[fld] = {"outcome": "insufficient_evidence", "reason": "no concept carries the field but identifier text shows it"}
        else:
            out[fld] = {"outcome": "resolved", "reason": "no concept and no identifier-text hint"}
    return out


def _position_identity(positions: list[dict], cik: str) -> tuple[dict, list[str]]:
    inherited = []
    typed_axes = Counter(d["axis"] for c in positions for d in c["dimensions"] if d["kind"] == "typed")
    if typed_axes:
        axis, n = typed_axes.most_common(1)[0]
        return {"axis": axis, "kind": "typed", "outcome": "resolved", "provenance": "derived", "inherited_from": None,
                "support": _prevalence(n, len(positions))}, inherited
    rule = rule_for(cik)
    if rule is not None:
        inherited.append("pipeline.explicit_contexts")
        return {"axis": rule.identity_axis, "kind": "explicit", "outcome": "resolved", "provenance": "inherited",
                "inherited_from": "pipeline.explicit_contexts.EXPLICIT_MEMBER_RULES", "support": None}, inherited
    return {"axis": None, "kind": None, "outcome": "insufficient_evidence", "provenance": "derived",
            "inherited_from": None, "support": None}, inherited


def census_instance(path: Path, cik: str, report_date: str, *, form_type: str = "", accession: str = "",
                    max_comparative_scans: int = 3, timeout_seconds: float = 120.0) -> dict:
    t0 = time.monotonic()
    path = Path(path)
    cik10 = str(cik).zfill(10)
    target = scan_instance(path, cik10, report_date, timeout_seconds=timeout_seconds)
    positions = [c for c in target["contexts"] if c["role"] == "confirmed_position"]
    inherited = ["pipeline.context_inventory.classify_context"]
    others = [p for p in target.get("document_period_ends", []) if p and p != report_date]
    others = sorted(others, reverse=True)[:max_comparative_scans]
    comp_ctx = []
    for p in others:
        comp = scan_instance(path, cik10, p, timeout_seconds=timeout_seconds)
        comp_ctx.extend(c for c in comp["contexts"] if _fact_value(c, "fair_value") is not None)
    cur_idents = {_identifier(c) for c in positions if _identifier(c)}
    comp_idents = [i for i in (_identifier(c) for c in comp_ctx) if i]
    paired = sum(1 for i in comp_idents if i in cur_idents)
    pid, inh2 = _position_identity(positions, cik10)
    inherited += inh2
    cmap, fills = _concept_map(positions)
    fund_ctx = [c for c in target["contexts"] if not c["dimensions"]]
    fund_concepts = sorted({_local(f["concept"]) for c in fund_ctx for f in c["facts"]})
    total_fv = next((_fact_value(c, "fair_value") for c in fund_ctx if _fact_value(c, "fair_value") is not None), None)
    census = {
        "schema_version": "census.v0", "cik": cik10, "report_date": report_date, "form_type": form_type,
        "accession": accession, "path": str(path), "sha256": target.get("sha256") or sha256_file(path),
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "elapsed_s": None,
        "source_complete": bool(target.get("source_complete")), "errors": list(target.get("errors", [])),
        "inherited": sorted(set(inherited)),
        "counts": {"positions": len(positions), "aggregates": target["counts"].get("aggregate", 0),
                   "unresolved": target["counts"].get("unresolved", 0), "comparative_contexts": len(comp_ctx)},
        "identifier_signature": _identifier_signature(positions, pid.get("axis") if pid["kind"] == "typed" else None),
        "concept_map": cmap, "fill_rates": fills,
        "subtotal_candidates": _subtotals(target["contexts"], positions),
        "presentation_views": _views(positions),
        "comparative_periods": {"periods": others, "contexts": len(comp_ctx), "distinguished_by": "context_period",
                                "paired_identifier_share": _prevalence(paired, len(comp_idents))},
        "status_markers": _status_markers(target["contexts"] + comp_ctx),
        "non_disclosure": _non_disclosure(positions, fills),
        "fund_level": {"concepts": fund_concepts, "total_investments_fv": total_fv},
        "position_identity": pid,
    }
    census["elapsed_s"] = round(time.monotonic() - t0, 2)
    return census


_SCHEMA = None


def validate_census(census: dict) -> list[str]:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(_SCHEMA)
    return [f"{e.json_path}: {e.message}" for e in sorted(v.iter_errors(census), key=lambda e: str(e.json_path))]


def write_census(paths: PilotPaths, census: dict) -> Path:
    out = paths.sub("census") / census["cik"] / f"{census['report_date']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(census, indent=1), encoding="utf-8")
    return out
```

- [ ] **Step 5: Write the census schema (loose on nested detail, strict on outcomes)**

Save as `scripts/profile_pilot/schemas/census_v0.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "census.v0",
  "type": "object",
  "required": ["schema_version", "cik", "report_date", "sha256", "recorded_at", "inherited", "counts",
               "identifier_signature", "concept_map", "fill_rates", "subtotal_candidates", "presentation_views",
               "comparative_periods", "status_markers", "non_disclosure", "fund_level", "position_identity"],
  "properties": {
    "schema_version": {"const": "census.v0"},
    "cik": {"type": "string", "pattern": "^[0-9]{10}$"},
    "report_date": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
    "inherited": {"type": "array", "items": {"type": "string"}},
    "counts": {"type": "object", "required": ["positions", "aggregates", "unresolved", "comparative_contexts"]},
    "subtotal_candidates": {"type": "array", "items": {"$ref": "#/$defs/outcome_obj"}},
    "presentation_views": {"type": "array", "items": {"$ref": "#/$defs/outcome_obj"}},
    "status_markers": {"type": "object", "additionalProperties": {"$ref": "#/$defs/outcome_obj"}},
    "non_disclosure": {"type": "object", "additionalProperties": {"$ref": "#/$defs/outcome_obj"}},
    "position_identity": {"allOf": [{"$ref": "#/$defs/outcome_obj"},
                                    {"required": ["provenance"], "properties": {"provenance": {"enum": ["derived", "inherited"]}}}]}
  },
  "$defs": {
    "outcome_obj": {"type": "object", "required": ["outcome"],
                    "properties": {"outcome": {"enum": ["resolved", "candidate", "insufficient_evidence"]}}}
  }
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_profile_pilot_census.py -q`
Expected: 10 passed. If `scan_instance` classifies a synthetic context as `unresolved` rather than `confirmed_position`, check the test builder writes the typed member exactly as `tests/test_context_inventory.py` does (`<f:Identifier>` child inside `typedMember`) and that facts carry `unitRef="USD"`.

- [ ] **Step 7: Commit**

```bash
git add tests/profile_pilot_xml.py scripts/profile_pilot/census.py scripts/profile_pilot/schemas/census_v0.schema.json tests/test_profile_pilot_census.py
git commit -m "Add census collectors with three-state detector outcomes

- Reuses context_inventory.scan_instance; comparative periods via extra period scans
- Subtotal, presentation-view, status-marker, non-disclosure detectors never assert
- Records inherited classification sources per census"
```

---

### Task 5: Census on cached instances (light CIKs) and performance bound

**Files:**
- Modify: `scripts/profile_pilot/census.py` (add `census_fund_quarter`)
- Test: `tests/test_profile_pilot_cache.py`

**Interfaces:**
- Consumes: `fund_quarters(paths, cik, mode)`, `census_instance`, `write_census`.
- Produces: `census_fund_quarter(paths, fq: dict, *, force=False) -> dict` that reads the instance at `fq["instance_path"]`, runs `census_instance(..., form_type=fq["form_type"], accession=fq["accession_number"])`, writes it, and returns it. When the census file already exists with the same `sha256` and `force` is False it is loaded instead of recomputed.

- [ ] **Step 1: Add `census_fund_quarter` to `census.py`**

```python
def census_fund_quarter(paths: PilotPaths, fq: dict, *, force: bool = False) -> dict:
    out = paths.sub("census") / fq["cik"] / f"{fq['report_date']}.json"
    src = Path(fq["instance_path"])
    if not fq.get("cached") or not src.is_file():
        raise FileNotFoundError(f"instance not cached: {src}")
    if out.is_file() and not force:
        prior = json.loads(out.read_text(encoding="utf-8"))
        if prior.get("sha256") == sha256_file(src):
            return prior
    census = census_instance(src, fq["cik"], fq["report_date"], form_type=fq["form_type"],
                             accession=fq["accession_number"])
    write_census(paths, census)
    return census
```

- [ ] **Step 2: Write the cache-backed tests**

```python
# tests/test_profile_pilot_cache.py
"""needs_cache: runs the census on real small instances (Stellus Q1, NexPoint Q1, Fidelity Q1)."""
import pytest

from scripts.profile_pilot import census as C
from scripts.profile_pilot.cohort import fund_quarters
from scripts.profile_pilot.paths import PilotPaths, resolve_data_root

pytestmark = pytest.mark.needs_cache


@pytest.fixture(scope="module")
def paths():
    try:
        return PilotPaths(resolve_data_root(None))
    except FileNotFoundError:
        pytest.skip("no data root")


@pytest.mark.parametrize("cik,expected_min_positions", [("0001901037", 50), ("0001588272", 40), ("0001920453", 20)])
def test_light_cik_q1_census_runs_within_bounds(paths, cik, expected_min_positions):
    fq = fund_quarters(paths, cik, "first2")[0]
    cen = C.census_fund_quarter(paths, fq, force=True)
    assert cen["counts"]["positions"] >= expected_min_positions, cen["counts"]
    assert cen["elapsed_s"] < 60, cen["elapsed_s"]
    assert cen["form_type"] in ("10-Q", "10-K")
    assert C.validate_census(cen) == []


def test_nexpoint_identity_is_inherited_explicit_member(paths):
    fq = fund_quarters(paths, "0001588272", "first2")[0]
    cen = C.census_fund_quarter(paths, fq)
    assert cen["position_identity"]["provenance"] == "inherited"
    assert "pipeline.explicit_contexts" in cen["inherited"]


def test_stellus_identity_is_derived_typed_axis(paths):
    fq = fund_quarters(paths, "0001901037", "first2")[0]
    cen = C.census_fund_quarter(paths, fq)
    assert cen["position_identity"]["kind"] == "typed" and cen["position_identity"]["provenance"] == "derived"
```

- [ ] **Step 3: Run the tests (light job; three ~1-3 MB instances)**

Run: `python -m pytest tests/test_profile_pilot_cache.py -q`
Expected: 5 passed. If NexPoint's Q1 census reports `kind == "typed"`, inspect `census/0001588272/2023-09-30.json`: NexPoint positions are explicit members on another axis per the spec; the typed axis may be a category rollup. Do NOT loosen the assertion; record the finding in the commit body and open an issue line in the investigation doc (Task 12).

- [ ] **Step 4: Commit**

```bash
git add scripts/profile_pilot/census.py tests/test_profile_pilot_cache.py
git commit -m "Run the census on cached Stellus, NexPoint and Fidelity Q1 instances

- census_fund_quarter caches by instance sha256
- Bounds: < 60 s per instance, schema-valid output
- NexPoint identity recorded as inherited from explicit_contexts"
```

---

### Task 6: Profile derivation, wrapper key inventory, M1 comparison

**Files:**
- Create: `scripts/profile_pilot/profile.py`
- Test: `tests/test_profile_pilot_profile.py`

**Interfaces:**
- Consumes: `envelope.make_entry`, `envelope.new_profile`, `envelope.validate_profile`, census dict (Task 4), wrapper v3 JSON.
- Produces: `derive_profile(census: dict, *, entity_name: str, recorded_at: str | None = None) -> dict` (a validated profile; every entry `valid_from = census["report_date"]`, `form_type = None`, `author = "census"`, `status = "derived"`; unresolved detector outputs become `packet_stubs`, a top-level list on the returned profile document under key `"packet_stubs"` which the schema must allow -- add `"packet_stubs": {"type": "array"}` to `filer_profile_v0.schema.json` properties).
- Produces: `wrapper_key_inventory(wrapper: dict) -> list[str]` flattened dotted keys, e.g. `identifier_format.delimiter`, `dispatch.aggregate_markers`, `staging.strategy`, `archetypes.senior_secured_debt`, `invariants.fv_reconciliation`, `known_edge_cases.<id>`, `segment_assertions`, `source_encodings`.
- Produces: `compare_to_wrapper(profile: dict, wrapper: dict, census: dict) -> dict` = `{"denominator": n, "classes": {key: class}, "counts": {exact, partial, inherited, unresolved, miss, not_derivable}, "per_section": {section: counts}}` with `M1_CLASSES = ("exact", "partial", "inherited", "unresolved", "miss", "not_derivable")`.
- Produces: `load_wrapper(paths, cik) -> dict | None`, `write_profile(paths, profile, suffix="") -> Path`.

Profile keys derived (spec 6.2 table):

| key | value from census | outcome mapping |
|---|---|---|
| `identifier_format.delimiter` | top delimiter | derived; `support` = its prevalence |
| `identifier_format.segment_counts` | `segment_counts` dict | derived |
| `identifier_format.prefix_vocabulary` | prefix list | derived (empty list if none) |
| `subtotals_and_headings.contexts` | resolved subtotal identifiers | derived; candidates -> packet stub |
| `presentation_views.duplicates` | resolved view groups (axis sets) | derived; candidates -> packet stub |
| `comparative_periods.rule` | `"context_period_ne_report_date"` | derived; `support` = context_count(comparatives) |
| `column_contract.<field>` | `{concept, fill}` for each field with a concept | derived; `standard` flag carried |
| `footnote_conventions.<status>` | location | derived only if resolved; else packet stub |
| `position_identity.axis` | axis | derived or inherited per census |
| `non_disclosure.<field>` | `True` | derived only if resolved; else packet stub |
| `fund_level_concepts.concepts` | concept list | derived |
| `accounting_scope.basis`, `anchors.total`, `lifecycle.first_quarter` | -- | packet stubs (spec: stub) |

M1 classification rules (exactly one class per wrapper key):

| wrapper key pattern | rule |
|---|---|
| `identifier_format.delimiter` | `exact` if equal to profile delimiter; `partial` if it appears in the census delimiter list; else `miss` |
| `identifier_format.alternate_delimiters` | `exact` if set equality with census delimiters minus the top one; `partial` if intersection; `miss` if census saw none |
| `identifier_format.field_order` | `partial` if `len(field_order)` equals the modal segment count; else `miss` |
| `dispatch.aggregate_markers` | `exact` if every marker appears (case-insensitive substring) in a resolved subtotal identifier; `partial` if some; `unresolved` if the only hits are candidates; `miss` if none |
| `dispatch.prefix_rules` | `exact` if every prefix is in `prefix_vocabulary`; `partial` if some; `miss` if none |
| `dispatch.no_prefix_is_aggregate`, `dispatch.category_marker_re`, `dispatch.leaf_markers_by_family`, `dispatch.non_private_markers`, `dispatch.fallback_family_patterns`, `dispatch.rule_prefix` | `not_derivable` |
| `staging.strategy` | `inherited` if census `position_identity.provenance == "inherited"`; `partial` if strategy is `hierarchy_leaf_guard` and census `presentation_views` has resolved groups; else `not_derivable` |
| `staging.*` other | `not_derivable` |
| `archetypes.*` | `not_derivable` (prose-defined families) |
| `invariants.fv_reconciliation` | `exact` if `fund_level.total_investments_fv` is not None; else `miss` |
| `invariants.*` other | `not_derivable` |
| `known_edge_cases.*` | `not_derivable` |
| `segment_assertions`, `source_encodings` | `partial` if census identifier signature shows the segment count / suffix pattern named; else `miss` |

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_pilot_profile.py
from scripts.profile_pilot import profile as PR
from scripts.profile_pilot.envelope import validate_profile


def _census():
    return {
        "schema_version": "census.v0", "cik": "0001901037", "report_date": "2022-09-30", "form_type": "10-Q",
        "accession": "a", "path": "p", "sha256": "0" * 64, "recorded_at": "2026-09-28T00:00:00Z", "elapsed_s": 1.0,
        "source_complete": True, "errors": [], "inherited": ["pipeline.context_inventory.classify_context"],
        "counts": {"positions": 3, "aggregates": 1, "unresolved": 0, "comparative_contexts": 2},
        "identifier_signature": {"axis": "f:InvestmentIdentifierAxis",
                                 "delimiters": [{"delimiter": " | ", "prevalence": {"numerator": 3, "denominator": 3}},
                                                {"delimiter": ", ", "prevalence": {"numerator": 1, "denominator": 3}}],
                                 "segment_counts": {"4": 2, "2": 1}, "prefix_vocabulary": [],
                                 "ordinal_suffix_share": {"numerator": 0, "denominator": 3}},
        "concept_map": {"fair_value": {"{http://fasb.org/us-gaap/2022}InvestmentOwnedAtFairValue": {"count": 3, "standard": True}}},
        "fill_rates": {"fair_value": {"numerator": 3, "denominator": 3}, "interest_rate": {"numerator": 0, "denominator": 3}},
        "subtotal_candidates": [{"context_id": "t1", "identifier": "Total First Lien", "fair_value": 150, "child_count": 2,
                                 "child_context_ids": ["c1", "c2"], "outcome": "resolved", "reason": "label"},
                                {"context_id": "c4", "identifier": "Delta | Unitranche", "fair_value": 150, "child_count": 2,
                                 "child_context_ids": ["c1", "c2"], "outcome": "candidate", "reason": "sum only"}],
        "presentation_views": [],
        "comparative_periods": {"periods": ["2021-12-31"], "contexts": 2, "distinguished_by": "context_period",
                                "paired_identifier_share": {"numerator": 2, "denominator": 2}},
        "status_markers": {"nonaccrual": {"location": "absent_in_instance", "outcome": "insufficient_evidence", "examples": []}},
        "non_disclosure": {"interest_rate": {"outcome": "insufficient_evidence", "reason": "text hint"},
                           "maturity": {"outcome": "resolved", "reason": "none"}},
        "fund_level": {"concepts": ["InvestmentOwnedAtFairValue", "Assets"], "total_investments_fv": 175.0},
        "position_identity": {"axis": "f:InvestmentIdentifierAxis", "kind": "typed", "outcome": "resolved",
                              "provenance": "derived", "inherited_from": None, "support": {"kind": "prevalence", "numerator": 3, "denominator": 3}},
    }


def _wrapper():
    return {"schema_version": "bdc-xbrl-wrapper.v3", "cik": "0001901037", "entity_name": "Stellus", "version": 4,
            "dispatch": {"rule_prefix": "STL", "prefix_rules": {}, "leaf_markers_by_family": {},
                         "aggregate_markers": ["total first lien", "total investments"], "non_private_markers": [],
                         "fallback_family_patterns": []},
            "staging": {"strategy": "hierarchy_leaf_guard"},
            "identifier_format": {"delimiter": " | ", "field_order": ["issuer", "instrument", "rate", "maturity"],
                                  "alternate_delimiters": [", "]},
            "archetypes": {"senior_secured_debt": {}}, "invariants": {"fv_reconciliation": {}, "rate_sanity": {}},
            "known_edge_cases": [{"id": "spv_suffix"}]}


def test_profile_entries_are_dated_and_validate():
    p = PR.derive_profile(_census(), entity_name="Stellus", recorded_at="2026-09-28T00:00:00Z")
    assert validate_profile(p) == []
    assert all(e["valid_from"] == "2022-09-30" and e["author"] == "census" for e in p["entries"])
    delim = next(e for e in p["entries"] if e["key"] == "identifier_format.delimiter")
    assert delim["value"] == " | " and delim["support"] == {"kind": "prevalence", "numerator": 3, "denominator": 3}


def test_unresolved_detectors_become_packet_stubs_not_entries():
    p = PR.derive_profile(_census(), entity_name="Stellus")
    keys = {e["key"] for e in p["entries"]}
    assert "non_disclosure.interest_rate" not in keys and "non_disclosure.maturity" in keys
    assert "footnote_conventions.nonaccrual" not in keys
    stub_keys = {s["key"] for s in p["packet_stubs"]}
    assert {"non_disclosure.interest_rate", "footnote_conventions.nonaccrual", "subtotals_and_headings.candidate:c4",
            "accounting_scope.basis", "anchors.total", "lifecycle.first_quarter"} <= stub_keys


def test_wrapper_key_inventory_is_flat_and_complete():
    keys = PR.wrapper_key_inventory(_wrapper())
    assert "identifier_format.delimiter" in keys and "dispatch.aggregate_markers" in keys
    assert "known_edge_cases.spv_suffix" in keys and "archetypes.senior_secured_debt" in keys
    assert len(keys) == len(set(keys))


def test_m1_classes_use_fixed_denominator_and_never_fold_partial_into_exact():
    census = _census()
    p = PR.derive_profile(census, entity_name="Stellus")
    m1 = PR.compare_to_wrapper(p, _wrapper(), census)
    assert m1["denominator"] == len(PR.wrapper_key_inventory(_wrapper()))
    assert sum(m1["counts"].values()) == m1["denominator"]
    assert m1["classes"]["identifier_format.delimiter"] == "exact"
    assert m1["classes"]["identifier_format.alternate_delimiters"] == "exact"
    assert m1["classes"]["identifier_format.field_order"] == "partial"
    assert m1["classes"]["dispatch.aggregate_markers"] == "partial"   # one of two markers seen resolved
    assert m1["classes"]["invariants.fv_reconciliation"] == "exact"
    assert m1["classes"]["known_edge_cases.spv_suffix"] == "not_derivable"


def test_inherited_identity_marks_staging_strategy_inherited():
    census = _census()
    census["position_identity"].update(provenance="inherited", kind="explicit",
                                       inherited_from="pipeline.explicit_contexts.EXPLICIT_MEMBER_RULES", support=None)
    p = PR.derive_profile(census, entity_name="X")
    ident = next(e for e in p["entries"] if e["key"] == "position_identity.axis")
    assert ident["provenance"] == "inherited"
    assert PR.compare_to_wrapper(p, _wrapper(), census)["classes"]["staging.strategy"] == "inherited"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_profile.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Allow `packet_stubs` in the profile schema**

In `scripts/profile_pilot/schemas/filer_profile_v0.schema.json`, add to the top-level `properties`:

```json
    "packet_stubs": {"type": "array", "items": {"type": "object", "required": ["key", "outcome", "reason"]}}
```

- [ ] **Step 4: Write the profile module**

```python
# scripts/profile_pilot/profile.py
"""Profile v0 derivation from a census, and the M1 comparison against the hand-authored wrapper (spec 6.2)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.profile_pilot.envelope import make_entry, new_profile, validate_profile
from scripts.profile_pilot.paths import PilotPaths

M1_CLASSES = ("exact", "partial", "inherited", "unresolved", "miss", "not_derivable")
_NOT_DERIVABLE_PREFIXES = ("archetypes.", "known_edge_cases.")
_NOT_DERIVABLE_KEYS = {"dispatch.no_prefix_is_aggregate", "dispatch.category_marker_re", "dispatch.leaf_markers_by_family",
                       "dispatch.non_private_markers", "dispatch.fallback_family_patterns", "dispatch.rule_prefix",
                       "dispatch.category_marker_before_total", "invariants.position_count_qoq", "invariants.rate_sanity",
                       "invariants.unclassified_rate"}


def load_wrapper(paths: PilotPaths, cik: str) -> dict | None:
    p = paths.overrides_dir / "bdc_xbrl_wrappers" / f"{str(cik).zfill(10)}.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _stub(key, outcome, reason, **extra):
    return {"key": key, "outcome": outcome, "reason": reason, **extra}


def derive_profile(census: dict, *, entity_name: str, recorded_at: str | None = None) -> dict:
    cik, vf = census["cik"], census["report_date"]
    prof = new_profile(cik, entity_name)
    stubs: list[dict] = []

    def add(key, value, **kw):
        prof["entries"].append(make_entry(key, value, valid_from=vf, cik=cik, recorded_at=recorded_at, **kw))

    sig = census["identifier_signature"]
    if sig["delimiters"]:
        top = sig["delimiters"][0]
        add("identifier_format.delimiter", top["delimiter"], support={"kind": "prevalence", **top["prevalence"]})
        add("identifier_format.alternate_delimiters", [d["delimiter"] for d in sig["delimiters"][1:]])
    else:
        stubs.append(_stub("identifier_format.delimiter", "insufficient_evidence", "no delimiter candidate seen"))
    add("identifier_format.segment_counts", sig["segment_counts"])
    add("identifier_format.prefix_vocabulary", [p["prefix"] for p in sig["prefix_vocabulary"]])

    resolved_subs = [s for s in census["subtotal_candidates"] if s["outcome"] == "resolved"]
    add("subtotals_and_headings.contexts", sorted({s["identifier"] for s in resolved_subs}),
        support={"kind": "context_count", "count": len(resolved_subs)})
    for s in census["subtotal_candidates"]:
        if s["outcome"] != "resolved":
            stubs.append(_stub(f"subtotals_and_headings.candidate:{s['context_id']}", s["outcome"], s["reason"],
                               identifier=s["identifier"], fair_value=s["fair_value"]))

    resolved_views = [v for v in census["presentation_views"] if v["outcome"] == "resolved"]
    add("presentation_views.duplicates", [v["axis_sets"] for v in resolved_views],
        support={"kind": "context_count", "count": sum(len(v["context_ids"]) for v in resolved_views)})
    for i, v in enumerate(census["presentation_views"]):
        if v["outcome"] != "resolved":
            stubs.append(_stub(f"presentation_views.candidate:{i}", v["outcome"], v["reason"], context_ids=v["context_ids"]))

    cp = census["comparative_periods"]
    add("comparative_periods.rule", "context_period_ne_report_date", support={"kind": "context_count", "count": cp["contexts"]},
        evidence=[{"kind": "periods", "values": cp["periods"]}])

    for field, concepts in census["concept_map"].items():
        best = max(concepts.items(), key=lambda kv: kv[1]["count"])
        add(f"column_contract.{field}", {"concept": best[0], "standard": best[1]["standard"],
                                          "fill": census["fill_rates"].get(field)},
            support={"kind": "prevalence", **census["fill_rates"].get(field, {"numerator": best[1]["count"],
                                                                              "denominator": census["counts"]["positions"]})})

    for status, m in census["status_markers"].items():
        if m["outcome"] == "resolved":
            add(f"footnote_conventions.{status}", m["location"], evidence=[{"kind": "examples", "values": m["examples"]}])
        else:
            stubs.append(_stub(f"footnote_conventions.{status}", m["outcome"], m.get("reason", "not visible in instance")))

    pid = census["position_identity"]
    if pid["outcome"] == "resolved":
        add("position_identity.axis", {"axis": pid["axis"], "kind": pid["kind"]}, provenance=pid["provenance"],
            inherited_from=pid["inherited_from"], support=pid.get("support"))
    else:
        stubs.append(_stub("position_identity.axis", pid["outcome"], "no typed axis and no explicit-member rule"))

    for field, nd in census["non_disclosure"].items():
        if nd["outcome"] == "resolved":
            add(f"non_disclosure.{field}", True)
        else:
            stubs.append(_stub(f"non_disclosure.{field}", nd["outcome"], nd["reason"]))

    add("fund_level_concepts.concepts", census["fund_level"]["concepts"])
    if census["fund_level"]["total_investments_fv"] is not None:
        add("fund_level_concepts.total_investments_fv", census["fund_level"]["total_investments_fv"])

    for key, reason in (("accounting_scope.basis", "structure cannot settle scope; needs packet"),
                        ("anchors.total", "copied from agent_anchor at contract time, not derived"),
                        ("lifecycle.first_quarter", "needs filings index and successor evidence")):
        stubs.append(_stub(key, "insufficient_evidence", reason))

    prof["packet_stubs"] = stubs
    errs = validate_profile(prof)
    if errs:
        raise ValueError("derived profile failed validation: " + "; ".join(errs[:5]))
    return prof


def wrapper_key_inventory(wrapper: dict) -> list[str]:
    keys: list[str] = []
    for section in ("dispatch", "staging", "identifier_format", "archetypes", "invariants"):
        sub = wrapper.get(section)
        if isinstance(sub, dict):
            keys += [f"{section}.{k}" for k in sub]
    for ec in wrapper.get("known_edge_cases") or []:
        keys.append(f"known_edge_cases.{ec.get('id', 'unnamed')}")
    for flat in ("segment_assertions", "source_encodings"):
        if flat in wrapper:
            keys.append(flat)
    return keys


def _entry(profile, key):
    return next((e for e in profile["entries"] if e["key"] == key), None)


def _classify_key(key: str, wrapper: dict, profile: dict, census: dict) -> str:
    section, _, leaf = key.partition(".")
    wval = wrapper.get(section, {}).get(leaf) if section in wrapper and isinstance(wrapper[section], dict) else wrapper.get(key)
    if key in _NOT_DERIVABLE_KEYS or key.startswith(_NOT_DERIVABLE_PREFIXES):
        return "not_derivable"
    sig = census["identifier_signature"]
    seen = [d["delimiter"] for d in sig["delimiters"]]
    if key == "identifier_format.delimiter":
        e = _entry(profile, key)
        if e is None:
            return "unresolved"
        return "exact" if e["value"] == wval else ("partial" if wval in seen else "miss")
    if key == "identifier_format.alternate_delimiters":
        want, got = set(wval or []), set(seen[1:])
        return "exact" if want == got else ("partial" if want & got else "miss")
    if key == "identifier_format.field_order":
        modal = max(sig["segment_counts"].items(), key=lambda kv: kv[1])[0] if sig["segment_counts"] else None
        return "partial" if modal is not None and int(modal) == len(wval or []) else "miss"
    if key == "dispatch.aggregate_markers":
        resolved = " || ".join(s["identifier"].lower() for s in census["subtotal_candidates"] if s["outcome"] == "resolved")
        cands = " || ".join(s["identifier"].lower() for s in census["subtotal_candidates"] if s["outcome"] != "resolved")
        markers = [m.lower() for m in (wval or [])]
        hits = [m for m in markers if m in resolved]
        if markers and len(hits) == len(markers):
            return "exact"
        if hits:
            return "partial"
        return "unresolved" if any(m in cands for m in markers) else "miss"
    if key == "dispatch.prefix_rules":
        vocab = {p["prefix"].lower() for p in sig["prefix_vocabulary"]}
        prefixes = [p.lower() for p in (wval or {})]
        hits = [p for p in prefixes if p in vocab]
        return "exact" if prefixes and len(hits) == len(prefixes) else ("partial" if hits else "miss")
    if key == "staging.strategy":
        if census["position_identity"]["provenance"] == "inherited":
            return "inherited"
        if wval == "hierarchy_leaf_guard" and any(v["outcome"] == "resolved" for v in census["presentation_views"]):
            return "partial"
        return "not_derivable"
    if section == "staging":
        return "not_derivable"
    if key == "invariants.fv_reconciliation":
        return "exact" if census["fund_level"]["total_investments_fv"] is not None else "miss"
    if key == "segment_assertions":
        return "partial" if sig["segment_counts"] else "miss"
    if key == "source_encodings":
        return "partial" if sig["ordinal_suffix_share"]["numerator"] > 0 else "miss"
    return "not_derivable"


def compare_to_wrapper(profile: dict, wrapper: dict, census: dict) -> dict:
    keys = wrapper_key_inventory(wrapper)
    classes = {k: _classify_key(k, wrapper, profile, census) for k in keys}
    counts = {c: sum(1 for v in classes.values() if v == c) for c in M1_CLASSES}
    per_section: dict[str, dict] = {}
    for k, c in classes.items():
        per_section.setdefault(k.split(".")[0], {x: 0 for x in M1_CLASSES})[c] += 1
    return {"denominator": len(keys), "classes": classes, "counts": counts, "per_section": per_section}


def write_profile(paths: PilotPaths, profile: dict, suffix: str = "") -> Path:
    out = paths.sub("profiles") / f"{profile['cik']}{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=1), encoding="utf-8")
    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_profile_pilot_profile.py tests/test_profile_pilot_envelope.py -q`
Expected: 13 passed

- [ ] **Step 6: Add the cache-backed M1 run for the light CIKs and the same-era profile**

Append to `tests/test_profile_pilot_cache.py`:

```python
def test_m1_for_light_ciks_uses_pinned_inventory(paths):
    import json
    from scripts.profile_pilot import profile as PR
    from scripts.profile_pilot.cohort import cohort_entry
    inv = {}
    for cik in ("0001901037", "0001588272", "0001920453"):
        wrapper = PR.load_wrapper(paths, cik)
        assert wrapper is not None
        inv[cik] = PR.wrapper_key_inventory(wrapper)
        for mode, suffix in (("first2", ""), ("authoring", ".authoring")):
            fq = fund_quarters(paths, cik, mode)[0]
            cen = C.census_fund_quarter(paths, fq)
            prof = PR.derive_profile(cen, entity_name=cohort_entry(cik)["name"])
            PR.write_profile(paths, prof, suffix)
            m1 = PR.compare_to_wrapper(prof, wrapper, cen)
            assert m1["denominator"] == len(inv[cik]) and sum(m1["counts"].values()) == m1["denominator"]
    (paths.results_dir / "wrapper_key_inventory.json").write_text(json.dumps(inv, indent=1), encoding="utf-8")
```

Run: `python -m pytest tests/test_profile_pilot_cache.py -q -k m1`
Expected: 1 passed. The `authoring` mode runs the census on each CIK's 2026-03-31 instance (7-9 MB for Stellus); still a light job.

- [ ] **Step 7: Commit**

```bash
git add scripts/profile_pilot/profile.py scripts/profile_pilot/schemas/filer_profile_v0.schema.json tests/test_profile_pilot_profile.py tests/test_profile_pilot_cache.py
git commit -m "Derive profile v0 from census and compare to the hand wrapper (M1)

- Unresolved detector outputs become packet stubs, never entries
- Six M1 classes against a fixed wrapper-key denominator; partial never counts as exact
- Same-era (authoring-quarter) profile derived alongside Q1"
```

---

### Task 7: Translate a profile to wrapper v3 JSON (for D2 parity)

**Files:**
- Create: `scripts/profile_pilot/translate.py`
- Test: `tests/test_profile_pilot_translate.py`

**Interfaces:**
- Consumes: profile dict (Task 6), the hand wrapper dict (for non-expressible sections to carry through unchanged so D2 isolates the profile's effect).
- Produces: `to_wrapper_v3(profile: dict, base_wrapper: dict, *, report_date: str) -> tuple[dict, list[str]]` returning the translated wrapper and a list of `not_expressible` profile keys. Expressible: `identifier_format.delimiter` -> `identifier_format.delimiter`; `identifier_format.alternate_delimiters` -> same; `subtotals_and_headings.contexts` -> `dispatch.aggregate_markers` (lower-cased identifiers, REPLACING the hand list); `identifier_format.prefix_vocabulary` -> `dispatch.prefix_rules` keys mapped to the family `"mixed"` when the hand wrapper had no rule for that prefix (keep hand families where present). Everything else is copied from `base_wrapper` verbatim and reported as not expressible when the profile has an entry for it (`presentation_views.*`, `comparative_periods.*`, `column_contract.*`, `footnote_conventions.*`, `position_identity.*`, `non_disclosure.*`, `fund_level_concepts.*`).
- Produces: `write_overlay_dir(paths, cik, wrapper: dict) -> Path` writing `<pilot>/parity/{cik10}/overlay/{cik10}.json` (the directory passed to `reload_wrapper_specs(override_dir=...)`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_pilot_translate.py
from scripts.profile_pilot import translate as T
from scripts.profile_pilot.envelope import make_entry, new_profile


def _profile():
    p = new_profile("0001901037", "Stellus")
    kw = dict(valid_from="2022-09-30", cik="0001901037", recorded_at="2026-09-28T00:00:00Z")
    p["entries"] += [
        make_entry("identifier_format.delimiter", " | ", **kw),
        make_entry("identifier_format.alternate_delimiters", [", "], **kw),
        make_entry("subtotals_and_headings.contexts", ["Total First Lien", "Total Investments"], **kw),
        make_entry("identifier_format.prefix_vocabulary", ["Controlled Affiliated Investments", "First Lien"], **kw),
        make_entry("presentation_views.duplicates", [["AffiliationAxis", "InvestmentIdentifierAxis"]], **kw),
        make_entry("comparative_periods.rule", "context_period_ne_report_date", **kw),
    ]
    p["packet_stubs"] = []
    return p


def _base():
    return {"schema_version": "bdc-xbrl-wrapper.v3", "cik": "0001901037", "entity_name": "Stellus", "version": 4,
            "dispatch": {"rule_prefix": "STL", "prefix_rules": {"First Lien": "senior_secured_debt"},
                         "leaf_markers_by_family": {}, "aggregate_markers": ["hand marker"], "non_private_markers": [],
                         "fallback_family_patterns": []},
            "staging": {"strategy": "hierarchy_leaf_guard"},
            "identifier_format": {"delimiter": ", ", "field_order": ["a", "b"], "alternate_delimiters": []},
            "archetypes": {}, "invariants": {}, "known_edge_cases": []}


def test_expressible_sections_replace_and_others_carry_through():
    w, not_expr = T.to_wrapper_v3(_profile(), _base(), report_date="2022-09-30")
    assert w["identifier_format"]["delimiter"] == " | " and w["identifier_format"]["alternate_delimiters"] == [", "]
    assert w["dispatch"]["aggregate_markers"] == ["total first lien", "total investments"]
    assert w["dispatch"]["prefix_rules"] == {"First Lien": "senior_secured_debt", "Controlled Affiliated Investments": "mixed"}
    assert w["staging"] == _base()["staging"] and w["identifier_format"]["field_order"] == ["a", "b"]
    assert sorted(not_expr) == ["comparative_periods.rule", "presentation_views.duplicates"]
    assert w["schema_version"] == "bdc-xbrl-wrapper.v3" and w["cik"] == "0001901037"


def test_overlay_dir_contains_one_wrapper_file(tmp_path):
    from scripts.profile_pilot.paths import PilotPaths
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "bdc_holdings.csv").write_text("cik\n", encoding="utf-8")
    pp = PilotPaths(tmp_path)
    w, _ = T.to_wrapper_v3(_profile(), _base(), report_date="2022-09-30")
    d = T.write_overlay_dir(pp, "0001901037", w)
    assert (d / "0001901037.json").is_file() and d.name == "overlay"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_translate.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the translate module**

```python
# scripts/profile_pilot/translate.py
"""Profile v0 -> wrapper v3 for the sections the wrapper can express (spec 6.4 D2)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.profile_pilot.envelope import resolve
from scripts.profile_pilot.paths import PilotPaths

EXPRESSIBLE = ("identifier_format.delimiter", "identifier_format.alternate_delimiters",
               "subtotals_and_headings.contexts", "identifier_format.prefix_vocabulary")
_SILENT = ("identifier_format.segment_counts", "fund_level_concepts.", "column_contract.", "non_disclosure.")


def to_wrapper_v3(profile: dict, base_wrapper: dict, *, report_date: str) -> tuple[dict, list[str]]:
    w = copy.deepcopy(base_wrapper)
    w.setdefault("dispatch", {}).setdefault("prefix_rules", {})
    w.setdefault("identifier_format", {})
    not_expressible: list[str] = []
    for key in sorted({e["key"] for e in profile["entries"]}):
        e = resolve(profile, key, report_date)
        if e is None:
            continue
        if key == "identifier_format.delimiter":
            w["identifier_format"]["delimiter"] = e["value"]
        elif key == "identifier_format.alternate_delimiters":
            w["identifier_format"]["alternate_delimiters"] = list(e["value"])
        elif key == "subtotals_and_headings.contexts":
            w["dispatch"]["aggregate_markers"] = [str(v).lower() for v in e["value"]]
        elif key == "identifier_format.prefix_vocabulary":
            for prefix in e["value"]:
                w["dispatch"]["prefix_rules"].setdefault(prefix, "mixed")
        elif key.startswith(_SILENT):
            continue  # informational sections with no wrapper counterpart and no D2 effect
        else:
            not_expressible.append(key)
    w["version"] = int(w.get("version", 1))
    w["source"] = w.get("source", "bdc_xbrl")
    w["_pilot_translation"] = {"profile_cik": profile["cik"], "report_date": report_date, "not_expressible": not_expressible}
    return w, not_expressible


def write_overlay_dir(paths: PilotPaths, cik: str, wrapper: dict) -> Path:
    d = paths.sub("parity") / str(cik).zfill(10) / "overlay"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{str(cik).zfill(10)}.json").write_text(json.dumps(wrapper, indent=1), encoding="utf-8")
    return d
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_profile_pilot_translate.py -q`
Expected: 2 passed

- [ ] **Step 5: Confirm the production loader accepts the translated wrapper**

Append to the test file and run it:

```python
def test_production_loader_parses_translated_wrapper(tmp_path):
    from pipeline.bdc_xbrl_wrapper import _load_specs_from_json
    w, _ = T.to_wrapper_v3(_profile(), _base(), report_date="2022-09-30")
    (tmp_path / "0001901037.json").write_text(__import__("json").dumps(w), encoding="utf-8")
    specs = _load_specs_from_json(tmp_path)
    assert "0001901037" in specs
    assert "total first lien" in specs["0001901037"].aggregate_markers
```

Run: `python -m pytest tests/test_profile_pilot_translate.py -q`
Expected: 3 passed. If `_load_specs_from_json` rejects the extra `_pilot_translation` key, move it into `known_edge_cases` as an entry with `id: "_pilot_translation"` instead.

- [ ] **Step 6: Commit**

```bash
git add scripts/profile_pilot/translate.py tests/test_profile_pilot_translate.py
git commit -m "Translate profile v0 to wrapper v3 for staging parity

- Delimiters, aggregate markers and prefix vocabulary are expressible
- Views, comparatives, contracts reported as not_expressible
- Verified the production wrapper loader parses the overlay"
```

---

### Task 8: Contracts, tolerance table, per-row grammar and fund-income yield (M2)

**Files:**
- Create: `scripts/profile_pilot/contracts.py`
- Test: `tests/test_profile_pilot_contracts.py`

**Interfaces:**
- Consumes: census dicts (Q1, Q2), profile (Q1), `pipeline.identifier_rate.load_grammar`, `apply_grammar`, bdc_holdings slice frames (columns as in bdc_holdings.csv, rates DECIMAL), `bdc_fund_income.csv`.
- Produces: `TOLERANCES: dict` = the spec 6.3 table, written once as `results/contract_tolerances.json` by `write_tolerances(paths)`.
- Produces: `learn_contracts(census_q1: dict, profile_q1: dict, grammar: dict | None) -> list[dict]` items `{cik, field, kind, partition: None|dict, expected, low_history: bool}` with `kind in ("concept_set", "fill_rate", "scale", "format_grammar", "value_range", "fund_income_yield")`.
- Produces: `evaluate_contracts(contracts, census_q2, rows_q2: pd.DataFrame, income_q2: dict | None, tolerances=TOLERANCES) -> list[dict]` adding `observed`, `status in ("holds", "holds_with_form_type", "breach", "insufficient_evidence")`, `partition_candidate: bool`, `reason`.
- Produces: `holdings_slice(paths, cik, report_date) -> pd.DataFrame` (DuckDB read of `bdc_holdings.csv` for one fund-quarter, current-period rows only, all columns as VARCHAR plus numeric casts `fv, cost_num, rate_num, pik_num, spread_num`).
- Produces: `fund_income(paths, cik, report_date) -> dict | None` (row from `bdc_fund_income.csv` for the fund-quarter with `duration_months` in 2..4, else None).
- Produces: `run_contracts(paths, cik) -> dict` writing `contracts/{cik10}.json` with `M2 = {holds, holds_with_form_type, breach, insufficient_evidence, denominator}`.

Grammar-less per-row format check: a row "parses" if the identifier contains the Q1 top delimiter AND its segment count is one of the Q1 segment counts with share >= 10%. With a grammar: a row parses if `apply_grammar` returns non-None for every `required_fields` entry. A partition candidate is raised when the parse rate is between 0.20 and 0.80 (spec 6.2: multi-modal signature).

Fund-income yield: `implied = interest_income * (12 / duration_months) / sum(fair_value of rows with rate_num not null)`; `declared = sum(fair_value * (rate_num + coalesce(pik_num, 0))) / sum(fair_value)` over the same rows (decimal rates). Contract holds if `0.6 <= implied / declared <= 1.4`; `insufficient_evidence` if income missing, duration not quarterly, or fewer than 10 rated rows.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_pilot_contracts.py
import pandas as pd

from scripts.profile_pilot import contracts as K


def _census(delim=" | ", segs=None, fills=None, positions=60):
    segs = segs or {"4": 55, "2": 5}
    fills = fills or {"fair_value": {"numerator": positions, "denominator": positions},
                      "interest_rate": {"numerator": 50, "denominator": positions}}
    return {"cik": "0001901037", "report_date": "2022-09-30", "form_type": "10-Q",
            "counts": {"positions": positions},
            "identifier_signature": {"delimiters": [{"delimiter": delim, "prevalence": {"numerator": positions, "denominator": positions}}],
                                     "segment_counts": segs},
            "concept_map": {"fair_value": {"{g}InvestmentOwnedAtFairValue": {"count": positions, "standard": True}},
                            "interest_rate": {"{g}InvestmentInterestRate": {"count": 50, "standard": True}}},
            "fill_rates": fills}


def _rows(n_a=50, n_b=0):
    rows = [dict(investment_identifier=f"Acme {i} | First Lien | 9.50% | 2027-06-30", fair_value=100.0, cost_num=99.0,
                 rate_num=0.095, pik_num=None, spread_num=None) for i in range(n_a)]
    rows += [dict(investment_identifier=f"Beta {i}, First Lien, SOFR + 650 bps", fair_value=100.0, cost_num=99.0,
                  rate_num=0.11, pik_num=None, spread_num=0.065) for i in range(n_b)]
    return pd.DataFrame(rows)


def test_tolerances_table_has_low_history_band():
    assert K.TOLERANCES["fill_rate"]["default"] == 0.10 and K.TOLERANCES["fill_rate"]["low_history"] == 0.25
    assert K.TOLERANCES["low_history_positions"] == 50


def test_concept_set_and_fill_rate_hold_on_identical_census():
    c1 = _census()
    contracts = K.learn_contracts(c1, profile_q1=None, grammar=None)
    res = K.evaluate_contracts(contracts, _census(), _rows(), income_q2=None)
    by = {(r["field"], r["kind"]): r for r in res}
    assert by[("fair_value", "concept_set")]["status"] == "holds"
    assert by[("interest_rate", "fill_rate")]["status"] == "holds"


def test_fill_rate_breach_outside_band():
    contracts = K.learn_contracts(_census(), None, None)
    q2 = _census(fills={"fair_value": {"numerator": 60, "denominator": 60}, "interest_rate": {"numerator": 20, "denominator": 60}})
    res = K.evaluate_contracts(contracts, q2, _rows(), None)
    assert next(r for r in res if r["kind"] == "fill_rate" and r["field"] == "interest_rate")["status"] == "breach"


def test_half_and_half_format_raises_partition_candidate_not_plain_breach():
    contracts = K.learn_contracts(_census(), None, None)
    res = K.evaluate_contracts(contracts, _census(), _rows(n_a=30, n_b=30), None)
    fg = next(r for r in res if r["kind"] == "format_grammar")
    assert fg["partition_candidate"] is True and fg["status"] == "breach"
    assert 0.45 < fg["observed"]["parse_rate"] < 0.55


def test_low_history_widens_band_and_is_flagged():
    contracts = K.learn_contracts(_census(positions=26, fills={"fair_value": {"numerator": 26, "denominator": 26},
                                                              "interest_rate": {"numerator": 20, "denominator": 26}}), None, None)
    assert all(c["low_history"] for c in contracts)
    q2 = _census(positions=59, fills={"fair_value": {"numerator": 59, "denominator": 59}, "interest_rate": {"numerator": 33, "denominator": 59}})
    res = K.evaluate_contracts(contracts, q2, _rows(), None)
    assert next(r for r in res if r["kind"] == "fill_rate" and r["field"] == "interest_rate")["status"] == "holds"


def test_fund_income_yield_holds_and_is_insufficient_without_income():
    contracts = K.learn_contracts(_census(), None, None)
    rows = _rows()
    ok = K.evaluate_contracts(contracts, _census(), rows, income_q2={"interest_income": 118.75, "duration_months": 3})
    y = next(r for r in ok if r["kind"] == "fund_income_yield")
    assert y["status"] == "holds" and abs(y["observed"]["ratio"] - 1.0) < 0.01
    none = K.evaluate_contracts(contracts, _census(), rows, income_q2=None)
    assert next(r for r in none if r["kind"] == "fund_income_yield")["status"] == "insufficient_evidence"


def test_form_type_change_marks_holds_with_form_type():
    contracts = K.learn_contracts(_census(), None, None)
    q2 = _census(fills={"fair_value": {"numerator": 60, "denominator": 60}, "interest_rate": {"numerator": 44, "denominator": 60}})
    q2["form_type"] = "10-K"
    res = K.evaluate_contracts(contracts, q2, _rows(), None)
    assert next(r for r in res if r["kind"] == "fill_rate" and r["field"] == "interest_rate")["status"] == "holds_with_form_type"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_contracts.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the contracts module**

```python
# scripts/profile_pilot/contracts.py
"""Per-filer, per-field, per-partition contracts learned from Q1 and evaluated on Q2 (spec 6.3)."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from scripts.profile_pilot.paths import REPO_ROOT, PilotPaths, git_head

TOLERANCES = {
    "low_history_positions": 50,
    "concept_set": {"default": "identical", "low_history": "identical"},
    "fill_rate": {"default": 0.10, "low_history": 0.25},
    "scale": {"default": "identical", "low_history": "identical"},
    "value_range": {"default": 0.25, "low_history": 0.50},
    "format_grammar": {"default": 1.00, "low_history": 0.90},
    "fund_income_yield": {"ratio_low": 0.6, "ratio_high": 1.4, "min_rated_rows": 10},
    "partition_candidate_band": [0.20, 0.80],
    "form_type_relief": 0.10,
}
KINDS = ("concept_set", "fill_rate", "scale", "format_grammar", "value_range", "fund_income_yield")
_RATE_FIELDS = ("interest_rate", "basis_spread", "pik_rate")


def write_tolerances(paths: PilotPaths) -> Path:
    paths.ensure_dirs()
    out = paths.results_dir / "contract_tolerances.json"
    if not out.exists():
        out.write_text(json.dumps(dict(recorded_at=datetime.now(timezone.utc).isoformat(), tolerances=TOLERANCES), indent=1),
                       encoding="utf-8")
    return out


def _low_history(census) -> bool:
    return census["counts"]["positions"] < TOLERANCES["low_history_positions"]


def _scale_of(field, census):
    # decimal vs percent is inferred from the fill; census values are not scaled, so scale = concept namespace kind
    concepts = census["concept_map"].get(field, {})
    return "standard" if any(v["standard"] for v in concepts.values()) else ("extension" if concepts else None)


def learn_contracts(census_q1: dict, profile_q1: dict | None, grammar: dict | None) -> list[dict]:
    cik, low = census_q1["cik"], _low_history(census_q1)
    out = []
    for field, concepts in census_q1["concept_map"].items():
        out.append(dict(cik=cik, field=field, kind="concept_set", partition=None, low_history=low,
                        expected=sorted(concepts)))
        out.append(dict(cik=cik, field=field, kind="scale", partition=None, low_history=low, expected=_scale_of(field, census_q1)))
    for field, fr in census_q1["fill_rates"].items():
        if fr["denominator"]:
            out.append(dict(cik=cik, field=field, kind="fill_rate", partition=None, low_history=low,
                            expected=fr["numerator"] / fr["denominator"]))
    sig = census_q1["identifier_signature"]
    if sig["delimiters"]:
        total = sum(sig["segment_counts"].values()) or 1
        modes = [int(k) for k, v in sig["segment_counts"].items() if v / total >= 0.10]
        out.append(dict(cik=cik, field="identifier", kind="format_grammar", partition=None, low_history=low,
                        expected=dict(delimiter=sig["delimiters"][0]["delimiter"], segment_counts=modes,
                                      grammar_required=list((grammar or {}).get("required_fields", [])))))
    out.append(dict(cik=cik, field="interest_rate", kind="fund_income_yield", partition=None, low_history=low,
                    expected=dict(ratio_low=TOLERANCES["fund_income_yield"]["ratio_low"],
                                  ratio_high=TOLERANCES["fund_income_yield"]["ratio_high"])))
    return out


def _parse_row(ident: str, expected: dict, grammar: dict | None) -> bool:
    if grammar and expected.get("grammar_required"):
        from pipeline.identifier_rate import apply_grammar
        parsed = apply_grammar(ident, grammar)
        return all(parsed.get(f) is not None for f in expected["grammar_required"])
    d = expected["delimiter"]
    return d in (ident or "") and len(ident.split(d)) in expected["segment_counts"]


def _band(kind, low):
    t = TOLERANCES[kind]
    return t["low_history"] if low else t["default"]


def evaluate_contracts(contracts, census_q2, rows_q2: pd.DataFrame, income_q2: dict | None,
                       tolerances=TOLERANCES, grammar: dict | None = None) -> list[dict]:
    form_changed = census_q2.get("form_type") and contracts and census_q2.get("form_type") != census_q2.get("_q1_form_type", census_q2.get("form_type"))
    res = []
    for c in contracts:
        r = dict(c, observed=None, status="insufficient_evidence", partition_candidate=False, reason="")
        k, f = c["kind"], c["field"]
        if k == "concept_set":
            got = sorted(census_q2["concept_map"].get(f, {}))
            r["observed"] = got
            r["status"] = "holds" if got == c["expected"] else ("breach" if got else "insufficient_evidence")
            r["reason"] = "" if got else "field absent in Q2"
        elif k == "scale":
            got = _scale_of(f, census_q2)
            r["observed"] = got
            r["status"] = "holds" if got == c["expected"] else ("breach" if got else "insufficient_evidence")
        elif k == "fill_rate":
            fr = census_q2["fill_rates"].get(f)
            if not fr or not fr["denominator"]:
                r["reason"] = "no positions in Q2"
            else:
                got = fr["numerator"] / fr["denominator"]
                r["observed"] = got
                diff = abs(got - c["expected"])
                band = _band("fill_rate", c["low_history"])
                if diff <= band:
                    r["status"] = "holds"
                elif form_changed and diff <= band + tolerances["form_type_relief"]:
                    r["status"] = "holds_with_form_type"
                else:
                    r["status"] = "breach"
        elif k == "format_grammar":
            idents = rows_q2["investment_identifier"].astype(str).tolist()
            if not idents:
                r["reason"] = "no rows"
            else:
                ok = sum(1 for i in idents if _parse_row(i, c["expected"], grammar))
                rate = ok / len(idents)
                r["observed"] = dict(parse_rate=rate, rows=len(idents))
                lo, hi = tolerances["partition_candidate_band"]
                r["partition_candidate"] = lo <= rate <= hi
                r["status"] = "holds" if rate >= _band("format_grammar", c["low_history"]) else "breach"
                if r["partition_candidate"]:
                    r["reason"] = "bimodal parse rate: search for a structural discriminator before calling this drift"
        elif k == "value_range":
            r["reason"] = "value_range learned from rows in run_contracts"  # filled by run_contracts (needs Q1 rows)
        elif k == "fund_income_yield":
            rated = rows_q2[rows_q2["rate_num"].notna() & rows_q2["fair_value"].notna()]
            if income_q2 is None or not (2 <= float(income_q2.get("duration_months") or 0) <= 4):
                r["reason"] = "no quarterly fund income row"
            elif len(rated) < tolerances["fund_income_yield"]["min_rated_rows"]:
                r["reason"] = "fewer than 10 rated rows"
            else:
                fv = rated["fair_value"].astype(float)
                declared = float((fv * (rated["rate_num"].astype(float) + rated["pik_num"].fillna(0).astype(float))).sum() / fv.sum())
                implied = float(income_q2["interest_income"]) * (12.0 / float(income_q2["duration_months"])) / float(fv.sum())
                ratio = implied / declared if declared else None
                r["observed"] = dict(implied=implied, declared=declared, ratio=ratio)
                if ratio is None:
                    r["reason"] = "declared yield is zero"
                else:
                    r["status"] = "holds" if c["expected"]["ratio_low"] <= ratio <= c["expected"]["ratio_high"] else "breach"
        res.append(r)
    return res


def holdings_slice(paths: PilotPaths, cik: str, report_date: str) -> pd.DataFrame:
    h = str(paths.output_dir / "bdc_holdings.csv").replace("\\", "/")
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(cost AS DOUBLE) AS cost_num, "
            f"TRY_CAST(interest_rate AS DOUBLE) AS rate_num, TRY_CAST(pik_rate AS DOUBLE) AS pik_num, "
            f"TRY_CAST(basis_spread AS DOUBLE) AS spread_num "
            f"FROM read_csv_auto('{h}', all_varchar=true) WHERE lpad(cik,10,'0') = ? AND report_date = ? AND period = report_date",
            [str(cik).zfill(10), report_date]).df()
    finally:
        con.close()


def fund_income(paths: PilotPaths, cik: str, report_date: str) -> dict | None:
    with open(paths.output_dir / "bdc_fund_income.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["cik"].zfill(10) == str(cik).zfill(10) and r["report_date"] == report_date and r.get("interest_income"):
                try:
                    dm = float(r["duration_months"])
                except (TypeError, ValueError):
                    continue
                if 2 <= dm <= 4:
                    return dict(interest_income=float(r["interest_income"]), duration_months=dm)
    return None


def _value_range(rows: pd.DataFrame, field: str):
    col = {"interest_rate": "rate_num", "basis_spread": "spread_num", "pik_rate": "pik_num"}[field]
    s = rows[col].dropna().astype(float)
    return (float(s.min()), float(s.max())) if len(s) else None


def run_contracts(paths: PilotPaths, cik: str, census_q1: dict, census_q2: dict, profile_q1: dict) -> dict:
    from pipeline.identifier_rate import GRAMMAR_DIR, load_grammar
    cik10 = str(cik).zfill(10)
    grammar = load_grammar(cik10) if (GRAMMAR_DIR / f"{cik10}.json").is_file() else None
    contracts = learn_contracts(census_q1, profile_q1, grammar)
    rows_q1 = holdings_slice(paths, cik10, census_q1["report_date"])
    rows_q2 = holdings_slice(paths, cik10, census_q2["report_date"])
    low = _low_history(census_q1)
    for f in _RATE_FIELDS:
        vr = _value_range(rows_q1, f)
        if vr:
            contracts.append(dict(cik=cik10, field=f, kind="value_range", partition=None, low_history=low, expected=list(vr)))
    q2 = dict(census_q2, _q1_form_type=census_q1.get("form_type"))
    res = evaluate_contracts(contracts, q2, rows_q2.rename(columns={"fv": "fair_value_num"}).assign(fair_value=lambda d: d["fair_value_num"]),
                             fund_income(paths, cik10, census_q2["report_date"]), grammar=grammar)
    widen = _band("value_range", low)
    for r in res:
        if r["kind"] == "value_range":
            s = rows_q2[{"interest_rate": "rate_num", "basis_spread": "spread_num", "pik_rate": "pik_num"}[r["field"]]].dropna().astype(float)
            if len(s) < 5:
                r["reason"] = "fewer than 5 values in Q2"
                continue
            lo, hi = r["expected"]
            span = (hi - lo) or abs(hi) or 1.0
            p5, p95 = float(s.quantile(0.05)), float(s.quantile(0.95))
            r["observed"] = dict(p5=p5, p95=p95)
            r["status"] = "holds" if (p5 >= lo - widen * span and p95 <= hi + widen * span) else "breach"
    m2 = {s: sum(1 for r in res if r["status"] == s) for s in ("holds", "holds_with_form_type", "breach", "insufficient_evidence")}
    m2["denominator"] = len(res)
    out = dict(cik=cik10, q1=census_q1["report_date"], q2=census_q2["report_date"], recorded_at=datetime.now(timezone.utc).isoformat(),
               git_head=git_head(REPO_ROOT), grammar_used=grammar is not None, contracts=res, M2=m2,
               partition_candidates=[r for r in res if r.get("partition_candidate")])
    p = paths.sub("contracts") / f"{cik10}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_profile_pilot_contracts.py -q`
Expected: 7 passed. The `form_type` test relies on `evaluate_contracts` seeing `_q1_form_type`; the test passes a Q2 census without it, so `form_changed` must default to comparing `form_type` against `_q1_form_type` when present and to `False` otherwise. If the test fails, set `q2["_q1_form_type"] = "10-Q"` in the test rather than loosening the code.

- [ ] **Step 5: Cache-backed M2 for the light CIKs**

Append to `tests/test_profile_pilot_cache.py`:

```python
def test_m2_contracts_for_light_ciks(paths):
    from scripts.profile_pilot import contracts as K, profile as PR
    from scripts.profile_pilot.cohort import cohort_entry
    K.write_tolerances(paths)
    for cik in ("0001901037", "0001588272", "0001920453"):
        q1, q2 = fund_quarters(paths, cik, "first2")
        c1, c2 = C.census_fund_quarter(paths, q1), C.census_fund_quarter(paths, q2)
        prof = PR.derive_profile(c1, entity_name=cohort_entry(cik)["name"])
        out = K.run_contracts(paths, cik, c1, c2, prof)
        assert out["M2"]["denominator"] == len(out["contracts"]) > 0
        assert sum(v for k, v in out["M2"].items() if k != "denominator") == out["M2"]["denominator"]
```

Run: `python -m pytest tests/test_profile_pilot_cache.py -q -k m2`
Expected: 1 passed. `contracts/{cik}.json` written for the three CIKs; `results/contract_tolerances.json` written once.

- [ ] **Step 6: Commit**

```bash
git add scripts/profile_pilot/contracts.py tests/test_profile_pilot_contracts.py tests/test_profile_pilot_cache.py
git commit -m "Add per-field contracts with fixed tolerance bands (M2)

- concept_set, fill_rate, scale, value_range, per-row format grammar, fund-income yield
- Bimodal parse rate raises a partition candidate instead of plain drift
- low_history widens bands; form-type change gives holds_with_form_type"
```

---

### Task 9: Interpretation and three-boundary compatibility parity (M4)

**Files:**
- Create: `scripts/profile_pilot/interpret.py`
- Create: `scripts/profile_pilot/parity.py`
- Test: `tests/test_profile_pilot_parity.py`

**Interfaces:**
- Consumes: census dict, profile dict, `translate.to_wrapper_v3`, `translate.write_overlay_dir`, `pipeline.bdc_xbrl_wrapper.reload_wrapper_specs`, `pipeline.staging_bdc._prepare_bdc`, `pipeline.staging_bdc._WRAPPER_DEFINITIONS_DIR`, `pipeline.agent_promoted.apply_promoted_plan`, `graduate.correction_inventory` items, `contracts.holdings_slice`.
- Produces (interpret): `d1_rows(census: dict, profile: dict) -> pd.DataFrame` with columns `accession_number, src_context_id, identifier, fair_value, cost, principal, interest_rate` built from census target contexts whose role is `confirmed_position`, MINUS contexts named in `subtotals_and_headings.contexts` (resolved) and MINUS the non-canonical members of resolved presentation-view groups (keep the context whose axis set is smallest). NOTE: `census_instance` must also store the raw target contexts it used; add a key `"_contexts"` (list of `{context_id, role, dimensions, facts}`) to the census dict in Task 4's `census_instance` and EXCLUDE it from `write_census` (write a copy without `_contexts`). Add `load_census_with_contexts(paths, fq)` that recomputes when `_contexts` is absent.
- Produces (parity): `d1(paths, census, profile) -> dict`, `d2(paths, cik, report_date, profile, base_wrapper) -> dict`, `d3(paths, cik, report_date, staged_profile_side: pd.DataFrame, corrections: list[dict], rules: dict) -> dict`, each returning `{boundary, row_key, reference: {path, sha256}, n_reference, n_profile, n_matched, n_unkeyed, missing_in_profile, extra_in_profile, fv_reference, fv_profile, fv_abs_diff, exact_rowset: bool, exact_fv: bool, per_column: {...}, not_expressible: [...]}`.
- Produces: `run_parity(paths, cik, report_date, census, profile, base_wrapper) -> dict` writing `parity/{cik10}/{report_date}.json` with `M4 = {D1: bool, D2: bool, D3_raw: bool, D3_replay: bool}`.

Rules from the spec (6.4): FV equality tolerance is 0.5 currency units per row and 1.0 on the sum. Row keys: D1 and D2 `(accession_number, src_context_id)`; D3 `row_id`, mapped from `(accession_number, src_context_id)` through the `private_markets_holdings.csv` slice. Rows with a null key are counted as `unkeyed`, never dropped silently. D2 and D3 restore the production wrapper state in a `finally` block (`reload_wrapper_specs()` with no argument and the saved `_WRAPPER_DEFINITIONS_DIR`).

- [ ] **Step 1: Write the failing tests (synthetic for D1 logic; cache for D2/D3)**

```python
# tests/test_profile_pilot_parity.py
import pandas as pd
import pytest

from scripts.profile_pilot import interpret as I, parity as PY
from scripts.profile_pilot.envelope import make_entry, new_profile


def _census_with_contexts():
    def ctx(cid, ident, fv, extra=None):
        dims = [dict(axis="f:InvestmentIdentifierAxis", value=ident, kind="typed")] + (extra or [])
        return dict(context_id=cid, role="confirmed_position", period="2022-09-30", dimensions=dims,
                    facts=[dict(field="fair_value", value=fv, concept="{g}FV")])
    return {"cik": "0001901037", "report_date": "2022-09-30", "accession": "0001558370-22-016375",
            "_contexts": [ctx("c1", "Acme | Loan", 100.0), ctx("c2", "Beta | Loan", 50.0),
                          ctx("t1", "Total Loans", 150.0),
                          ctx("v1", "Acme | Loan", 100.0, [dict(axis="f:AffiliationAxis", value="f:ControlledMember", kind="explicit")])],
            "subtotal_candidates": [{"context_id": "t1", "identifier": "Total Loans", "outcome": "resolved"}],
            "presentation_views": [{"context_ids": ["c1", "v1"], "outcome": "resolved"}]}


def _profile():
    p = new_profile("0001901037", "Stellus")
    kw = dict(valid_from="2022-09-30", cik="0001901037")
    p["entries"] += [make_entry("subtotals_and_headings.contexts", ["Total Loans"], **kw),
                     make_entry("presentation_views.duplicates", [["AffiliationAxis", "InvestmentIdentifierAxis"]], **kw)]
    return p


def test_d1_rows_drop_resolved_subtotals_and_duplicate_views():
    df = I.d1_rows(_census_with_contexts(), _profile())
    assert sorted(df["src_context_id"]) == ["c1", "c2"]
    assert df["fair_value"].sum() == 150.0 and (df["accession_number"] == "0001558370-22-016375").all()


def test_compare_reports_unkeyed_and_exactness():
    ref = pd.DataFrame(dict(accession_number=["a", "a", "a"], src_context_id=["c1", "c2", None], fair_value=[100.0, 50.0, 7.0]))
    got = pd.DataFrame(dict(accession_number=["a", "a"], src_context_id=["c1", "c2"], fair_value=[100.0, 50.0]))
    r = PY.compare_frames(ref, got, key=("accession_number", "src_context_id"), value_cols=("fair_value",))
    assert r["n_unkeyed"] == 1 and r["n_matched"] == 2 and r["exact_rowset"] is False
    assert r["missing_in_profile"] == [] and r["fv_abs_diff"] == 7.0


def test_compare_exact_when_identical():
    ref = pd.DataFrame(dict(accession_number=["a"], src_context_id=["c1"], fair_value=[100.0]))
    r = PY.compare_frames(ref, ref.copy(), key=("accession_number", "src_context_id"), value_cols=("fair_value",))
    assert r["exact_rowset"] and r["exact_fv"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_parity.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Extend `census_instance` to retain contexts (Task 4 file)**

In `scripts/profile_pilot/census.py`, inside `census_instance` after building `census`, add:

```python
    census["_contexts"] = [dict(context_id=c["context_id"], role=c["role"], period=c["period"],
                                dimensions=c["dimensions"], facts=c["facts"]) for c in target["contexts"]]
```

and change `write_census` to write `{k: v for k, v in census.items() if k != "_contexts"}`. Add:

```python
def load_census_with_contexts(paths: PilotPaths, fq: dict) -> dict:
    """Census dict including _contexts; recomputes when the stored file lacks them (it always does)."""
    return census_instance(Path(fq["instance_path"]), fq["cik"], fq["report_date"], form_type=fq["form_type"],
                           accession=fq["accession_number"])
```

Run `python -m pytest tests/test_profile_pilot_census.py -q` and confirm 10 still pass (schema ignores `_contexts` because the census schema does not set `additionalProperties: false`).

- [ ] **Step 4: Write interpret and parity**

```python
# scripts/profile_pilot/interpret.py
"""D1: profile-driven position rows from census contexts (no re-implemented extractor; spec 6.4)."""
from __future__ import annotations

import pandas as pd

from scripts.profile_pilot.envelope import resolve


def _val(ctx, field):
    for f in ctx["facts"]:
        if f["field"] == field and f["value"] is not None:
            return float(f["value"])
    return None


def _ident(ctx):
    typed = [d for d in ctx["dimensions"] if d["kind"] == "typed"]
    return typed[0]["value"] if typed else None


def d1_rows(census: dict, profile: dict) -> pd.DataFrame:
    rd = census["report_date"]
    sub = resolve(profile, "subtotals_and_headings.contexts", rd)
    subtotal_idents = {str(v).lower() for v in (sub["value"] if sub else [])}
    drop = {s["context_id"] for s in census.get("subtotal_candidates", [])
            if s["outcome"] == "resolved" and str(s.get("identifier", "")).lower() in subtotal_idents}
    views = resolve(profile, "presentation_views.duplicates", rd)
    if views is not None:
        by_id = {c["context_id"]: c for c in census["_contexts"]}
        for g in census.get("presentation_views", []):
            if g["outcome"] != "resolved":
                continue
            members = [by_id[c] for c in g["context_ids"] if c in by_id]
            keep = min(members, key=lambda c: (len(c["dimensions"]), c["context_id"]))
            drop |= {c["context_id"] for c in members if c is not keep}
    rows = []
    for c in census["_contexts"]:
        if c["role"] != "confirmed_position" or c["period"] != rd or c["context_id"] in drop:
            continue
        rows.append(dict(accession_number=census.get("accession"), src_context_id=c["context_id"], identifier=_ident(c),
                         fair_value=_val(c, "fair_value"), cost=_val(c, "cost"), principal=_val(c, "principal"),
                         interest_rate=_val(c, "interest_rate")))
    return pd.DataFrame(rows, columns=["accession_number", "src_context_id", "identifier", "fair_value", "cost",
                                       "principal", "interest_rate"])
```

```python
# scripts/profile_pilot/parity.py
"""Compatibility parity at three pinned boundaries (spec 6.4). Compatibility with production, not correctness."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from pipeline import bdc_xbrl_wrapper, staging_bdc
from pipeline.agent_promoted import apply_promoted_plan
from scripts.profile_pilot.contracts import holdings_slice
from scripts.profile_pilot.interpret import d1_rows
from scripts.profile_pilot.paths import REPO_ROOT, PilotPaths, git_head, sha256_file
from scripts.profile_pilot.translate import to_wrapper_v3, write_overlay_dir

ROW_TOL, SUM_TOL = 0.5, 1.0


def compare_frames(ref: pd.DataFrame, got: pd.DataFrame, *, key: tuple, value_cols=("fair_value",)) -> dict:
    key = list(key)
    ref_k = ref.dropna(subset=key)
    n_unkeyed = int(len(ref) - len(ref_k)) + int(len(got) - len(got.dropna(subset=key)))
    got_k = got.dropna(subset=key)
    m = ref_k.merge(got_k, on=key, how="outer", suffixes=("_ref", "_got"), indicator=True)
    missing = m[m["_merge"] == "left_only"][key].astype(str).agg("|".join, axis=1).tolist()
    extra = m[m["_merge"] == "right_only"][key].astype(str).agg("|".join, axis=1).tolist()
    both = m[m["_merge"] == "both"]
    per_col = {}
    for c in value_cols:
        a, b = pd.to_numeric(both.get(f"{c}_ref"), errors="coerce"), pd.to_numeric(both.get(f"{c}_got"), errors="coerce")
        agree = int(((a - b).abs() <= ROW_TOL).sum() + (a.isna() & b.isna()).sum())
        per_col[c] = dict(matched=int(len(both)), agree=agree)
    fv_ref = float(pd.to_numeric(ref["fair_value"], errors="coerce").fillna(0).sum())
    fv_got = float(pd.to_numeric(got["fair_value"], errors="coerce").fillna(0).sum())
    return dict(n_reference=int(len(ref)), n_profile=int(len(got)), n_matched=int(len(both)), n_unkeyed=n_unkeyed,
                missing_in_profile=missing[:200], extra_in_profile=extra[:200], fv_reference=fv_ref, fv_profile=fv_got,
                fv_abs_diff=abs(fv_ref - fv_got), exact_rowset=(not missing and not extra and n_unkeyed == 0),
                exact_fv=abs(fv_ref - fv_got) <= SUM_TOL, per_column=per_col)


def _ref(paths, name):
    p = paths.output_dir / name
    return dict(path=str(p), sha256=sha256_file(p))


def d1(paths: PilotPaths, census: dict, profile: dict) -> dict:
    ref = holdings_slice(paths, census["cik"], census["report_date"])[["accession_number", "src_context_id", "fv", "cost_num"]]
    ref = ref.rename(columns={"fv": "fair_value", "cost_num": "cost"})
    got = d1_rows(census, profile)
    out = compare_frames(ref, got, key=("accession_number", "src_context_id"), value_cols=("fair_value", "cost"))
    return dict(boundary="D1", row_key="accession_number+src_context_id", reference=_ref(paths, "bdc_holdings.csv"), **out)


def _staged(raw: pd.DataFrame) -> pd.DataFrame:
    return staging_bdc._prepare_bdc(bdc_df=raw)


def d2(paths: PilotPaths, cik: str, report_date: str, profile: dict, base_wrapper: dict) -> tuple[dict, pd.DataFrame]:
    raw = holdings_slice(paths, cik, report_date).drop(columns=["fv", "cost_num", "rate_num", "pik_num", "spread_num"])
    reference = _staged(raw)
    wrapper, not_expr = to_wrapper_v3(profile, base_wrapper, report_date=report_date)
    overlay = write_overlay_dir(paths, cik, wrapper)
    saved_dir = staging_bdc._WRAPPER_DEFINITIONS_DIR
    try:
        bdc_xbrl_wrapper.reload_wrapper_specs(override_dir=overlay)
        staging_bdc._WRAPPER_DEFINITIONS_DIR = overlay
        got = _staged(raw)
    finally:
        staging_bdc._WRAPPER_DEFINITIONS_DIR = saved_dir
        bdc_xbrl_wrapper.reload_wrapper_specs()
    key = ("accession_number", "src_context_id")
    out = compare_frames(reference, got, key=key, value_cols=("fair_value",))
    for col in ("issuer_name", "instrument_description", "extracted_industry"):
        if col in reference.columns and col in got.columns:
            m = reference.merge(got, on=list(key), suffixes=("_r", "_g"))
            out["per_column"][col] = dict(matched=int(len(m)), agree=int((m[f"{col}_r"].astype(str) == m[f"{col}_g"].astype(str)).sum()))
    return dict(boundary="D2", row_key="accession_number+src_context_id", reference={"path": "staging_bdc._prepare_bdc(bdc_holdings slice)",
                "sha256": _ref(paths, "bdc_holdings.csv")["sha256"]}, not_expressible=not_expr, **out), got


def _pmh_slice(paths, cik, report_date) -> pd.DataFrame:
    u = str(paths.output_dir / "private_markets_holdings.csv").replace("\\", "/")
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT row_id, accession_number, src_context_id, TRY_CAST(fair_value AS DOUBLE) AS fair_value, "
                           f"index_classification, corrected_fields FROM read_csv_auto('{u}', all_varchar=true) "
                           f"WHERE source='bdc' AND lpad(cik,10,'0') = ? AND report_date = ?", [str(cik).zfill(10), report_date]).df()
    finally:
        con.close()


def d3(paths: PilotPaths, cik: str, report_date: str, staged: pd.DataFrame, corrections: list[dict], rules: dict) -> dict:
    ref = _pmh_slice(paths, cik, report_date)
    keymap = ref[["accession_number", "src_context_id", "row_id"]].dropna()
    got = staged.merge(keymap, on=["accession_number", "src_context_id"], how="left")
    raw = compare_frames(ref, got, key=("row_id",), value_cols=("fair_value",))
    applicable_c = [c for c in corrections if str(c.get("cik")).zfill(10) == str(cik).zfill(10)
                    and (report_date in ((c.get("scope") or {}).get("quarters") or []) or (c.get("template") or {}).get("report_date") == report_date)]
    applicable_r = {k: [r for r in v if "all" in ((r.get("scope") or {}).get("quarters") or []) or report_date in ((r.get("scope") or {}).get("quarters") or [])]
                    for k, v in rules.items() if str(k).zfill(10) == str(cik).zfill(10)}
    replayed, audits = apply_promoted_plan(got.copy(), applicable_c, applicable_r) if (applicable_c or any(applicable_r.values())) else (got, [])
    rep = compare_frames(ref, replayed, key=("row_id",), value_cols=("fair_value",))
    return dict(boundary="D3", row_key="row_id", reference=_ref(paths, "private_markets_holdings.csv"),
                corrections_replayed=[c.get("fix_class") for c in applicable_c] + [r.get("rule_id") for v in applicable_r.values() for r in v],
                raw=raw, with_replay=rep)


def run_parity(paths: PilotPaths, cik: str, report_date: str, census: dict, profile: dict, base_wrapper: dict) -> dict:
    from pipeline.agent_promoted import load_promoted_corrections, load_promoted_rules
    r1 = d1(paths, census, profile)
    r2, staged = d2(paths, cik, report_date, profile, base_wrapper)
    r3 = d3(paths, cik, report_date, staged, load_promoted_corrections(paths.overrides_dir / "agent_b2_corrections"),
            load_promoted_rules(paths.overrides_dir / "agent_investigate_rules"))
    out = dict(cik=str(cik).zfill(10), report_date=report_date, recorded_at=datetime.now(timezone.utc).isoformat(),
               git_head=git_head(REPO_ROOT), D1=r1, D2=r2, D3=r3,
               M4=dict(D1=r1["exact_rowset"] and r1["exact_fv"], D2=r2["exact_rowset"] and r2["exact_fv"],
                       D3_raw=r3["raw"]["exact_rowset"] and r3["raw"]["exact_fv"],
                       D3_replay=r3["with_replay"]["exact_rowset"] and r3["with_replay"]["exact_fv"]))
    p = paths.sub("parity") / str(cik).zfill(10) / f"{report_date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out
```

- [ ] **Step 5: Run the synthetic tests**

Run: `python -m pytest tests/test_profile_pilot_parity.py tests/test_profile_pilot_census.py -q`
Expected: 13 passed

- [ ] **Step 6: Cache-backed parity for Stellus Q1 and record what D2 needs**

Append to `tests/test_profile_pilot_cache.py`:

```python
def test_parity_stellus_q1_writes_all_three_boundaries(paths):
    from scripts.profile_pilot import parity as PY, profile as PR
    fq = fund_quarters(paths, "0001901037", "first2")[0]
    cen = C.load_census_with_contexts(paths, fq)
    prof = PR.derive_profile(cen, entity_name="Stellus Private Credit")
    out = PY.run_parity(paths, "0001901037", fq["report_date"], cen, prof, PR.load_wrapper(paths, "0001901037"))
    assert set(out["M4"]) == {"D1", "D2", "D3_raw", "D3_replay"}
    assert out["D1"]["n_reference"] > 0 and out["D2"]["n_reference"] > 0 and out["D3"]["raw"]["n_reference"] > 0
```

Run: `python -m pytest tests/test_profile_pilot_cache.py -q -k parity`
Expected: 1 passed. `_prepare_bdc` on a 62-row slice takes seconds. If it raises because it expects columns the slice lacks, pass `bdc_df` with exactly the bdc_holdings column set (drop the numeric helper columns, as `d2` does) and record the exact exception in the commit body. If `_prepare_bdc` reads the FULL production file when `bdc_df` is given but empty, guard with `assert not raw.empty`. Do not fix by editing `pipeline/`.

- [ ] **Step 7: Commit**

```bash
git add scripts/profile_pilot/interpret.py scripts/profile_pilot/parity.py scripts/profile_pilot/census.py tests/test_profile_pilot_parity.py tests/test_profile_pilot_cache.py
git commit -m "Add three-boundary compatibility parity (M4)

- D1 from census contexts keyed accession+context id; no re-implemented extractor
- D2 via production staging with the translated profile overlaid, restored in finally
- D3 keyed row_id with explicit correction replay, reported raw and replayed"
```

---

### Task 10: All-quarter half-life with censoring (M5)

**Files:**
- Create: `scripts/profile_pilot/halflife.py`
- Test: `tests/test_profile_pilot_halflife.py`

**Interfaces:**
- Consumes: `fund_quarters(paths, cik, "all")`, `census_fund_quarter`, `contracts.learn_contracts`, `contracts.evaluate_contracts`, `contracts.holdings_slice`, `contracts.fund_income`, cohort `q1`.
- Produces: `km_median(observations: list[dict]) -> dict` where each observation is `{"t": int, "event": bool}` (quarters since derivation; `event=False` = censored), returning `{"median": int | None, "n": int, "events": int, "censored": int, "survival": [[t, S(t)], ...]}`. Median = smallest `t` with `S(t) <= 0.5`; `None` ("not reached") if never.
- Produces: `run_halflife(paths, cik, census_q1, profile_q1, known_events: dict) -> dict` writing `halflife/{cik10}.json` with per-contract first-break quarter (as `t`), `coincides_with` in `{"form_type_change", "known_dated_event", "none", None}`, and `M5 = km_median(...)` plus `breaks_by_coincidence` counts. `known_events` = `{cik10: [report_date, ...]}` from the spec section 4 list: BCRED `2025-12-31`, Stepstone `2025-12-31`, TCW `2026-03-31`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_pilot_halflife.py
from scripts.profile_pilot import halflife as H


def test_km_median_reached():
    obs = [dict(t=1, event=True), dict(t=2, event=True), dict(t=3, event=True), dict(t=5, event=False)]
    r = H.km_median(obs)
    assert r["median"] == 2 and r["events"] == 3 and r["censored"] == 1


def test_km_median_not_reached_when_most_are_censored():
    obs = [dict(t=4, event=False), dict(t=4, event=False), dict(t=4, event=False), dict(t=2, event=True)]
    r = H.km_median(obs)
    assert r["median"] is None and r["censored"] == 3


def test_censored_observation_does_not_count_as_break_at_horizon():
    r = H.km_median([dict(t=6, event=False)])
    assert r["events"] == 0 and r["survival"][-1][1] == 1.0


def test_coincidence_labels():
    assert H.coincidence("2022-12-31", form_types={"2022-09-30": "10-Q", "2022-12-31": "10-K"}, events=[]) == "form_type_change"
    assert H.coincidence("2025-12-31", form_types={"2025-09-30": "10-Q", "2025-12-31": "10-Q"}, events=["2025-12-31"]) == "known_dated_event"
    assert H.coincidence("2023-06-30", form_types={"2023-03-31": "10-Q", "2023-06-30": "10-Q"}, events=[]) == "none"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_halflife.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the halflife module**

```python
# scripts/profile_pilot/halflife.py
"""All-quarter extension [F]: first contract breach per section in quarters since derivation, KM-censored (spec 6.6)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.profile_pilot import census as C, contracts as K
from scripts.profile_pilot.cohort import fund_quarters
from scripts.profile_pilot.paths import REPO_ROOT, PilotPaths, git_head

KNOWN_EVENTS = {"0001803498": ["2025-12-31"], "0001950803": ["2025-12-31"], "0001715933": ["2026-03-31"]}


def km_median(observations: list[dict]) -> dict:
    obs = sorted(observations, key=lambda o: (o["t"], not o["event"]))
    n = len(obs)
    at_risk, s, curve, median = n, 1.0, [[0, 1.0]], None
    for t in sorted({o["t"] for o in obs}):
        d = sum(1 for o in obs if o["t"] == t and o["event"])
        if at_risk > 0 and d:
            s *= (1 - d / at_risk)
        curve.append([t, round(s, 4)])
        if median is None and s <= 0.5:
            median = t
        at_risk -= sum(1 for o in obs if o["t"] == t)
    return dict(median=median, n=n, events=sum(1 for o in obs if o["event"]),
                censored=sum(1 for o in obs if not o["event"]), survival=curve)


def coincidence(report_date: str, *, form_types: dict, events: list) -> str:
    if report_date in events:
        return "known_dated_event"
    dates = sorted(form_types)
    i = dates.index(report_date) if report_date in dates else -1
    if i > 0 and form_types[dates[i - 1]] != form_types[report_date]:
        return "form_type_change"
    return "none"


def run_halflife(paths: PilotPaths, cik: str, census_q1: dict, profile_q1: dict, known_events: dict = KNOWN_EVENTS) -> dict:
    cik10 = str(cik).zfill(10)
    fqs = [fq for fq in fund_quarters(paths, cik10, "all") if fq["cached"]]
    later = [fq for fq in fqs if fq["report_date"] > census_q1["report_date"]]
    form_types = {fq["report_date"]: fq["form_type"] for fq in fqs}
    from pipeline.identifier_rate import GRAMMAR_DIR, load_grammar
    grammar = load_grammar(cik10) if (GRAMMAR_DIR / f"{cik10}.json").is_file() else None
    contracts = K.learn_contracts(census_q1, profile_q1, grammar)
    first_break: dict[str, dict | None] = {f"{c['field']}:{c['kind']}": None for c in contracts}
    per_quarter = []
    for t, fq in enumerate(later, start=1):
        cen = C.census_fund_quarter(paths, fq)
        rows = K.holdings_slice(paths, cik10, fq["report_date"]).rename(columns={"fv": "fair_value_num"})
        rows = rows.assign(fair_value=rows["fair_value_num"])
        res = K.evaluate_contracts(contracts, dict(cen, _q1_form_type=census_q1["form_type"]), rows,
                                   K.fund_income(paths, cik10, fq["report_date"]), grammar=grammar)
        statuses = {f"{r['field']}:{r['kind']}": r["status"] for r in res}
        per_quarter.append(dict(t=t, report_date=fq["report_date"], form_type=fq["form_type"], statuses=statuses))
        for key, st in statuses.items():
            if st == "breach" and first_break[key] is None:
                first_break[key] = dict(t=t, report_date=fq["report_date"],
                                        coincides_with=coincidence(fq["report_date"], form_types=form_types, events=known_events.get(cik10, [])))
    horizon = len(later)
    obs = [dict(t=(fb["t"] if fb else horizon), event=bool(fb)) for fb in first_break.values()]
    m5 = km_median(obs) if horizon else dict(median=None, n=0, events=0, censored=0, survival=[[0, 1.0]])
    coinc = {}
    for fb in first_break.values():
        if fb:
            coinc[fb["coincides_with"]] = coinc.get(fb["coincides_with"], 0) + 1
    out = dict(cik=cik10, derived_from=census_q1["report_date"], horizon_quarters=horizon,
               recorded_at=datetime.now(timezone.utc).isoformat(), git_head=git_head(REPO_ROOT),
               first_break=first_break, per_quarter=per_quarter, M5=m5, breaks_by_coincidence=coinc,
               caveat="first break of a fixed Q1 profile; says nothing about later-derived profiles")
    p = paths.sub("halflife") / f"{cik10}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_profile_pilot_halflife.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit** (the cache-backed half-life run is a heavy job and belongs to Task 12)

```bash
git add scripts/profile_pilot/halflife.py tests/test_profile_pilot_halflife.py
git commit -m "Add all-quarter half-life with Kaplan-Meier censoring (M5)

- Time in quarters since derivation; never-broken sections are censored
- First break labelled by coincidence with form-type change or known event
- Caveat recorded: a fixed Q1 profile says nothing about later-derived ones"
```

---

### Task 11: Runner CLI, heavy-lock guard, summary report

**Files:**
- Create: `scripts/profile_pilot/run.py`
- Create: `scripts/profile_pilot/report.py`
- Test: `tests/test_profile_pilot_run.py`

**Interfaces:**
- Produces: `heavy_jobs_running() -> list[str]` (process command lines matching `pytest`, `rebuild_outputs.py`, `pipeline.programme.bootstrap`, `build_v13`, `evaluate_v13`, `snapshot_repaired_candidate` via `tasklist /v /fo csv` and `wmic process get commandline` on Windows; `ps -eo args` elsewhere).
- Produces: CLI `python -m scripts.profile_pilot.run --data-root <dir> --stage {manifest,graduate,census,profile,contracts,parity,halflife,summary,all} --cik <cik10|all> [--force] [--allow-heavy]`. Stages `census`/`parity`/`halflife` for Ares and BCRED (`cohort.heavy`) and `halflife` for any CIK refuse to start when `heavy_jobs_running()` is non-empty unless `--allow-heavy`, and print the offending command lines.
- Produces: `build_summary(paths) -> dict` (`report.py`) assembling M1-M5 from the JSON artifacts into `results/summary.json` with, per metric, the fixed denominator and every class as its own share; plus `render_investigation(summary) -> str` (markdown, ASCII) for Task 12.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_pilot_run.py
import json

from scripts.profile_pilot import report as R, run as RUN


def test_heavy_jobs_matcher_flags_known_names():
    lines = ["python -m pytest tests", "python scripts/rebuild_outputs.py --unified", "notepad.exe",
             "powershell build_v13.ps1", "python snapshot_repaired_candidate.py --candidate p"]
    assert RUN.match_heavy(lines) == [lines[0], lines[1], lines[3], lines[4]]


def test_summary_reports_every_class_against_fixed_denominator(tmp_path):
    (tmp_path / "output").mkdir(); (tmp_path / "output" / "bdc_holdings.csv").write_text("cik\n", encoding="utf-8")
    from scripts.profile_pilot.paths import PilotPaths
    pp = PilotPaths(tmp_path); pp.ensure_dirs()
    (pp.results_dir / "graduation.json").write_text(json.dumps(dict(denominator=4, per_class=dict(
        generalises=1, quarter_bound=1, conflicts=0, insufficient_evidence=1, not_expressible=1), per_fix_class={}, M3={})), encoding="utf-8")
    (pp.results_dir / "wrapper_key_inventory.json").write_text(json.dumps({"0001901037": ["a", "b"]}), encoding="utf-8")
    (pp.sub("profiles")).mkdir(exist_ok=True)
    (pp.sub("profiles") / "0001901037.m1.json").write_text(json.dumps(dict(denominator=2, counts=dict(
        exact=1, partial=1, inherited=0, unresolved=0, miss=0, not_derivable=0), per_section={})), encoding="utf-8")
    s = R.build_summary(pp)
    assert s["M3"]["denominator"] == 4 and sum(s["M3"]["shares"].values()) == 1.0
    assert s["M1"]["0001901037"]["exact_share"] == 0.5 and s["M1"]["0001901037"]["partial_share"] == 0.5
    assert "M4" in s and "M5" in s and "M2" in s
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_pilot_run.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `report.py`**

```python
# scripts/profile_pilot/report.py
"""Assemble M1-M5 from the pilot artifacts. Every class is its own share of a fixed denominator."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.profile_pilot.paths import REPO_ROOT, PilotPaths, git_head


def _load(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _shares(counts: dict, denom: int) -> dict:
    return {k: (round(v / denom, 4) if denom else None) for k, v in counts.items()}


def build_summary(paths: PilotPaths) -> dict:
    res = paths.results_dir
    out = dict(recorded_at=datetime.now(timezone.utc).isoformat(), git_head=git_head(REPO_ROOT), M1={}, M2={}, M3={}, M4={}, M5={})
    for p in sorted(paths.sub("profiles").glob("*.m1.json")):
        m1 = _load(p)
        cik = p.name.split(".")[0]
        out["M1"][cik] = {**{f"{k}_share": v for k, v in _shares(m1["counts"], m1["denominator"]).items()},
                          "denominator": m1["denominator"], "per_section": m1.get("per_section", {})}
    for p in sorted(paths.sub("profiles").glob("*.authoring.m1.json")):
        m1 = _load(p)
        out["M1"].setdefault("authoring_quarter", {})[p.name.split(".")[0]] = {
            **{f"{k}_share": v for k, v in _shares(m1["counts"], m1["denominator"]).items()}, "denominator": m1["denominator"]}
    for p in sorted(paths.sub("contracts").glob("*.json")):
        c = _load(p)
        d = c["M2"]["denominator"]
        out["M2"][c["cik"]] = {**_shares({k: v for k, v in c["M2"].items() if k != "denominator"}, d), "denominator": d,
                               "partition_candidates": len(c.get("partition_candidates", []))}
    g = _load(res / "graduation.json")
    if g:
        out["M3"] = dict(denominator=g["denominator"], shares=_shares(g["per_class"], g["denominator"]), per_fix_class=g.get("per_fix_class", {}))
    m4 = {}
    for p in sorted(paths.sub("parity").glob("*/*.json")):
        r = _load(p)
        if r and "M4" in r:
            m4[f"{r['cik']}:{r['report_date']}"] = r["M4"]
    if m4:
        out["M4"] = dict(fund_quarters=len(m4), D1=sum(v["D1"] for v in m4.values()), D2=sum(v["D2"] for v in m4.values()),
                         D3_raw=sum(v["D3_raw"] for v in m4.values()), D3_replay=sum(v["D3_replay"] for v in m4.values()), detail=m4)
    else:
        out["M4"] = dict(fund_quarters=0)
    m5 = {}
    for p in sorted(paths.sub("halflife").glob("*.json")):
        r = _load(p)
        if r:
            m5[r["cik"]] = dict(median=r["M5"]["median"], censored=r["M5"]["censored"], events=r["M5"]["events"],
                                horizon=r["horizon_quarters"], breaks_by_coincidence=r["breaks_by_coincidence"])
    out["M5"] = m5 or {"note": "half-life stage not run"}
    (res / "summary.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def render_investigation(summary: dict) -> str:
    lines = [f"## {datetime.now(timezone.utc).date().isoformat()} Filer profile pilot: M1-M5 (git {summary['git_head'][:8]})", "",
             "Question: how much of a per-filer profile can be derived from filing structure, how much survives a quarter, ",
             "how many corrections generalise, how compatible a derived profile is with production, and how long a Q1 profile lasts.", "",
             "### M1 derivation (per CIK, share of fixed wrapper-key denominator)", "",
             "| CIK | exact | partial | inherited | unresolved | miss | not_derivable | n |", "|---|---|---|---|---|---|---|---|"]
    for cik, m in summary["M1"].items():
        if cik == "authoring_quarter":
            continue
        lines.append(f"| {cik} | {m['exact_share']} | {m['partial_share']} | {m['inherited_share']} | {m['unresolved_share']} | {m['miss_share']} | {m['not_derivable_share']} | {m['denominator']} |")
    lines += ["", "### M2 re-use (Q2 contracts)", "", "| CIK | holds | holds_with_form_type | breach | insufficient_evidence | n | partition candidates |", "|---|---|---|---|---|---|---|"]
    for cik, m in summary["M2"].items():
        lines.append(f"| {cik} | {m['holds']} | {m['holds_with_form_type']} | {m['breach']} | {m['insufficient_evidence']} | {m['denominator']} | {m['partition_candidates']} |")
    m3 = summary.get("M3") or {}
    lines += ["", f"### M3 graduation: denominator {m3.get('denominator')} -> {json.dumps(m3.get('shares'))}", "",
              f"### M4 compatibility parity: {json.dumps({k: v for k, v in summary['M4'].items() if k != 'detail'})}", "",
              f"### M5 half-life (KM median, quarters since derivation, censored counts): {json.dumps(summary['M5'])}", "",
              "Parity is compatibility with production, not correctness. M5 describes a fixed Q1 profile only."]
    return "\n".join(lines) + "\n"
```

Also change Task 6's cache test to write the M1 comparison beside the profile: after `m1 = PR.compare_to_wrapper(...)`, add
`(paths.sub("profiles") / f"{cik}{suffix}.m1.json").write_text(json.dumps(m1, indent=1), encoding="utf-8")`.

- [ ] **Step 4: Write `run.py`**

```python
# scripts/profile_pilot/run.py
"""CLI for the filer-profile pilot. ASCII output only. Refuses heavy stages while heavy jobs run."""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys

from scripts.profile_pilot import census as C, contracts as K, graduate as G, halflife as H, parity as PY, profile as PR, report as R
from scripts.profile_pilot.cohort import COHORT, cohort_entry, fund_quarters
from scripts.profile_pilot.manifest import write_manifest
from scripts.profile_pilot.paths import PilotPaths, resolve_data_root

HEAVY_MARKERS = ("pytest", "rebuild_outputs.py", "pipeline.programme.bootstrap", "build_v13", "evaluate_v13",
                 "snapshot_repaired_candidate", "task0_v13", "build_v13_twin", "drills_v13")
STAGES = ("manifest", "graduate", "census", "profile", "contracts", "parity", "halflife", "summary", "all")


def match_heavy(cmdlines: list[str]) -> list[str]:
    return [c for c in cmdlines if any(m in c for m in HEAVY_MARKERS)]


def heavy_jobs_running() -> list[str]:
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["wmic", "process", "get", "commandline"], capture_output=True, text=True, timeout=30).stdout
        else:
            out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    me = " ".join(sys.argv)
    return [l.strip() for l in match_heavy(out.splitlines()) if l.strip() and me not in l]


def _guard(stage: str, cik: str, allow: bool) -> None:
    heavy_cik = cohort_entry(cik)["heavy"] if cik != "all" else True
    if stage in ("census", "parity", "halflife") and (heavy_cik or stage == "halflife") and not allow:
        running = heavy_jobs_running()
        if running:
            print("REFUSED: heavy job(s) running; spec section 10 one-heavy-job rule:")
            for r in running[:10]:
                print("  " + r[:160])
            sys.exit(3)


def _ciks(arg: str) -> list[str]:
    return [c["cik"] for c in COHORT] if arg == "all" else [str(arg).zfill(10)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="filer-profile pilot runner")
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--stage", choices=STAGES, required=True)
    ap.add_argument("--cik", default="all")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--allow-heavy", action="store_true")
    a = ap.parse_args(argv)
    paths = PilotPaths(resolve_data_root(a.data_root))
    paths.ensure_dirs()
    stages = [s for s in STAGES if s not in ("all",)] if a.stage == "all" else [a.stage]
    for stage in stages:
        _guard(stage, a.cik, a.allow_heavy)
        print(f"[pilot] stage={stage} cik={a.cik} data_root={paths.data_root}")
        if stage == "manifest":
            print("  wrote " + str(write_manifest(paths)))
        elif stage == "graduate":
            g = G.run_graduation(paths)
            print(f"  M3 denominator={g['denominator']} per_class={g['per_class']}")
        elif stage == "summary":
            s = R.build_summary(paths)
            print("  wrote results/summary.json; M4=" + json.dumps({k: v for k, v in s["M4"].items() if k != "detail"}))
        else:
            for cik in _ciks(a.cik):
                _run_cik_stage(paths, stage, cik, a.force)
    return 0


def _run_cik_stage(paths: PilotPaths, stage: str, cik: str, force: bool) -> None:
    entry = cohort_entry(cik)
    q1, q2 = fund_quarters(paths, cik, "first2")
    if stage == "census":
        for fq in (q1, q2, *fund_quarters(paths, cik, "authoring")):
            cen = C.census_fund_quarter(paths, fq, force=force)
            print(f"  census {cik} {fq['report_date']} positions={cen['counts']['positions']} elapsed={cen['elapsed_s']}s")
        return
    c1, c2 = C.census_fund_quarter(paths, q1), C.census_fund_quarter(paths, q2)
    wrapper = PR.load_wrapper(paths, cik)
    prof = PR.derive_profile(c1, entity_name=entry["name"])
    if stage == "profile":
        PR.write_profile(paths, prof)
        if wrapper:
            m1 = PR.compare_to_wrapper(prof, wrapper, c1)
            (paths.sub("profiles") / f"{cik}.m1.json").write_text(json.dumps(m1, indent=1), encoding="utf-8")
            ca = C.census_fund_quarter(paths, fund_quarters(paths, cik, "authoring")[0])
            pa = PR.derive_profile(ca, entity_name=entry["name"])
            PR.write_profile(paths, pa, ".authoring")
            (paths.sub("profiles") / f"{cik}.authoring.m1.json").write_text(
                json.dumps(PR.compare_to_wrapper(pa, wrapper, ca), indent=1), encoding="utf-8")
            print(f"  M1 {cik} q1={m1['counts']}")
    elif stage == "contracts":
        K.write_tolerances(paths)
        out = K.run_contracts(paths, cik, c1, c2, prof)
        print(f"  M2 {cik} {out['M2']}")
    elif stage == "parity":
        for fq in (q1, q2):
            cen = C.load_census_with_contexts(paths, fq)
            out = PY.run_parity(paths, cik, fq["report_date"], cen, PR.derive_profile(c1, entity_name=entry["name"]), wrapper)
            print(f"  M4 {cik} {fq['report_date']} {out['M4']}")
    elif stage == "halflife":
        out = H.run_halflife(paths, cik, c1, prof)
        print(f"  M5 {cik} median={out['M5']['median']} censored={out['M5']['censored']} horizon={out['horizon_quarters']}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_profile_pilot_run.py -q`
Expected: 2 passed

- [ ] **Step 6: Smoke the CLI on the light stages**

Run: `python -m scripts.profile_pilot.run --stage manifest` then `python -m scripts.profile_pilot.run --stage profile --cik 0001901037` and `python -m scripts.profile_pilot.run --stage summary`
Expected: ASCII lines starting `[pilot]`, no traceback, `results/summary.json` exists.

- [ ] **Step 7: Commit**

```bash
git add scripts/profile_pilot/run.py scripts/profile_pilot/report.py tests/test_profile_pilot_run.py tests/test_profile_pilot_cache.py
git commit -m "Add pilot runner with heavy-lock guard and M1-M5 summary

- Stages per CIK; census/parity on Ares and BCRED and all half-life runs refuse while heavy jobs run
- Summary reports every class as a share of its fixed denominator
- Investigation markdown renderer"
```

---

### Task 12: Execute the pilot, write up, changelog

**Files:**
- Create: `docs/investigations/filer_profile_pilot.md`
- Modify: `docs/agent_changelog.md` (append)
- Modify: `docs/investigations/INDEX.md` via `python scripts/split_investigations.py --reindex`

This task runs the pilot end to end. It is the only task that touches the heavy CIKs and the all-quarter stage. Follow the order exactly.

- [ ] **Step 1: Light stages for all six light CIKs (any time)**

```bash
python -m scripts.profile_pilot.run --stage manifest
python -m scripts.profile_pilot.run --stage graduate
for c in 0001901037 0001715933 0001920453 0001860424 0001950803 0001588272; do
  python -m scripts.profile_pilot.run --stage census --cik $c
  python -m scripts.profile_pilot.run --stage profile --cik $c
  python -m scripts.profile_pilot.run --stage contracts --cik $c
  python -m scripts.profile_pilot.run --stage parity --cik $c
done
```

Expected: each command prints `[pilot]` lines and exits 0. Any traceback is a stop-and-report; do not patch `pipeline/`.

- [ ] **Step 2: Check the heavy lock, then run Ares and BCRED**

Run `python -c "from scripts.profile_pilot.run import heavy_jobs_running as h; print(h())"`. If it prints a non-empty list, STOP and report which processes are running (the V13 controllers are expected until the build finishes; spec section 10 last-rebuild rule). When empty:

```bash
for c in 0001287750 0001803498; do
  python -m scripts.profile_pilot.run --stage census --cik $c
  python -m scripts.profile_pilot.run --stage profile --cik $c
  python -m scripts.profile_pilot.run --stage contracts --cik $c
  python -m scripts.profile_pilot.run --stage parity --cik $c
done
```

Expected: census on a 1,000-row instance completes in under 60 s and under 2 GiB (watch Task Manager; record elapsed from the census JSON). If it exceeds 60 s, record the time and continue; the bound is a reported constraint, not a gate.

- [ ] **Step 3: Half-life for all eight (heavy: 11-15 censuses per CIK)**

```bash
python -m scripts.profile_pilot.run --stage halflife --cik all
python -m scripts.profile_pilot.run --stage summary
```

- [ ] **Step 4: Write the investigation entry**

```bash
python -c "import json; from scripts.profile_pilot.report import render_investigation; from scripts.profile_pilot.paths import PilotPaths, resolve_data_root; p=PilotPaths(resolve_data_root(None)); print(render_investigation(json.load(open(p.results_dir/'summary.json', encoding='utf-8'))))" > docs/investigations/filer_profile_pilot.md
python scripts/split_investigations.py --reindex
```

Then edit `docs/investigations/filer_profile_pilot.md` by hand to add, under the rendered tables: the decision-table reading from spec section 9 applied to the actual numbers; the list of `insufficient_evidence` items and partition candidates per CIK; every D1/D2 divergence for any fund-quarter that is not 16/16 (row keys, from `parity/*/*.json`); the NexPoint identity finding from Task 5; the M1 gap between Q1-derived and authoring-quarter profiles per CIK; and the sections with no independent correctness check (rates, footnote conventions, position identity). Keep numbers in tables, ASCII only. Do not recommend a migration; the owner decides (spec section 9).

- [ ] **Step 5: Full pilot test run and backstop**

Run: `python -m pytest tests/test_profile_pilot_*.py -q --durations=20`
Expected: all pass; report the count. Then confirm the worktree's `data/output/` still does not exist (`ls data/output` errors) so the conftest protected-file snapshot had nothing to protect, and state in the changelog that `diff_outputs.py --semantic` was not applicable from the worktree.

- [ ] **Step 6: Changelog entry**

Append to `docs/agent_changelog.md`:

```
## <date> -- Filer-profile pilot executed (M1-M5 measured)

- New package `scripts/profile_pilot/` (paths, cohort, manifest, envelope, census, profile, translate, contracts, graduate, interpret, parity, halflife, report, run) with tests `tests/test_profile_pilot_*.py` (<N> tests; <M> are needs_cache). No `pipeline/` change.
- Artifacts under `<data_root>/pilot/filer_profile/` (git-ignored): manifest, wrapper_key_inventory, correction_inventory (denominator <K>), contract_tolerances, graduation, census/, profiles/ (Q1 and authoring-quarter), contracts/, parity/, halflife/, summary.json.
- Results: M1 <...>, M2 <...>, M3 <...>, M4 D1 <x>/16 D2 <y>/16 D3 raw <z>/16 replay <w>/16, M5 <...>. Write-up: `docs/investigations/filer_profile_pilot.md`.
- Constraints honoured: worktree-only, heavy stages ran after the V13 controllers released the lock at <time>; semantic diff backstop not applicable (no outputs in worktree).
- Open: <NexPoint identity finding>, <partition candidates>, <D2 not_expressible sections>.
```

- [ ] **Step 7: Commit and hand off**

```bash
git add docs/investigations/filer_profile_pilot.md docs/investigations/INDEX.md docs/agent_changelog.md
git commit -m "Record filer-profile pilot results (M1-M5)

- Investigation entry with per-CIK tables and divergence lists
- Changelog entry with artifact inventory and constraints honoured
- No pipeline or data/output change"
```

Do NOT push. Do NOT rebase onto main until the V13 merge has landed (spec section 2). Report the five numbers and the open items to the owner.

---

## Self-review against the spec (done while writing; re-run after execution)

- Spec 2 (isolation, data root, paths): Task 1 and Global Constraints. Covered.
- Spec 5 (cohort, form types from the accession, authoring quarter, two quarters now): Task 1 `cohort.py`; form type read from the filings index, not inferred. Covered. Three/four-quarter follow-on is out of scope by ruling.
- Spec 6.1 census incl. inherited tag and new collectors: Task 4/5. Covered. Footnote text is NOT visible to the census; status markers therefore return `insufficient_evidence` when absent from dimensions and concepts (recorded in the spec's risk list).
- Spec 6.2 envelope, two clocks, partitions, six M1 classes, packet stubs: Tasks 2 and 6. Covered. Partition DETECTION inside the census (multi-modal signature -> discriminator search) is implemented only as the contracts partition candidate (Task 8); the census records delimiter prevalence and segment counts but does not search discriminators. Gap accepted for the pilot and must be listed in the write-up as an open item.
- Spec 6.3 contracts, tolerance table, minimal suite: Task 8. Covered. Non-accrual count deferred by ruling.
- Spec 6.4 three boundaries, replay, not_expressible, inherited code list: Task 9. Covered. The inherited-code list per CIK (explicit_contexts, Stepstone rescale, Ares literals) is recorded through the census `inherited` field only for explicit_contexts; the runner should add a static note for the other CIK literals in the write-up (Task 12 Step 4).
- Spec 6.5 graduation with fidelity, source-backed check, insufficient_evidence: Task 3. Covered; the source-backed check is the anchor reconciliation, as the spec allows.
- Spec 6.6 half-life with censoring: Task 10. Covered.
- Spec 8 deliverables (package, tests incl. schema tests for both supersession kinds and as-of, pinned inputs, cost note, [E] first): Tasks 1-12 in that order. Covered.
- Spec 9 metrics with fixed denominators: Tasks 3, 6, 8, 9, 10, 11. Covered.
- Spec 10 heavy-lock and last-rebuild rule: Task 11 guard and Task 12 ordering. Covered.
- Type consistency checked: `fund_quarters(paths, cik, mode)` returns dicts with `cik, report_date, form_type, filing_date, accession_number, instance_path, cached`; `census_fund_quarter(paths, fq, force=False)`; `derive_profile(census, *, entity_name, recorded_at=None)`; `compare_to_wrapper(profile, wrapper, census)`; `learn_contracts(census_q1, profile_q1, grammar)`; `evaluate_contracts(contracts, census_q2, rows_q2, income_q2, tolerances=TOLERANCES, grammar=None)`; `run_parity(paths, cik, report_date, census, profile, base_wrapper)`; `run_halflife(paths, cik, census_q1, profile_q1, known_events=KNOWN_EVENTS)`.
