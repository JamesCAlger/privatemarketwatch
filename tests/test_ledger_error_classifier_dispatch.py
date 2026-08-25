"""Tests for scripts/ledger_error_classifier/build_dispatch.py.

TDD: these were written BEFORE the implementation.  Run to confirm failure,
implement, run again to confirm green.

Fixture: 3-row provenance worklist (2 cohort CIKs + 1 out-of-cohort).
All file I/O is under pytest's tmp_path; cohort_guard and review_bundles are
monkeypatched so no real data is touched.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import target (will fail before implementation exists)
# ---------------------------------------------------------------------------

from scripts.ledger_error_classifier import build_dispatch  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COHORT_CIKS = {"0001234567", "0009876543"}
OUT_OF_COHORT_CIK = "0000000001"

_WORKLIST_ROWS = [
    {
        "review_id": "RVQ_BLK_001",
        "cik": "0001234567",
        "report_date": "2025-12-31",
        "reason_code": "filing_mismatch",
        "n_units": "5",
        "fv_at_risk_m": "12.5",
        "confidence": "0.9",
        "priority_rank": "1",
    },
    {
        "review_id": "RVQ_BLK_002",
        "cik": "0009876543",
        "report_date": "2025-09-30",
        "reason_code": "anchor_missing",
        "n_units": "3",
        "fv_at_risk_m": "7.2",
        "confidence": "0.85",
        "priority_rank": "2",
    },
    {
        "review_id": "RVQ_BLK_003",
        "cik": OUT_OF_COHORT_CIK,
        "report_date": "2025-06-30",
        "reason_code": "transform_drift",
        "n_units": "1",
        "fv_at_risk_m": "0.5",
        "confidence": "0.7",
        "priority_rank": "3",
    },
]

_COHORT_ONLY_ROWS = [r for r in _WORKLIST_ROWS if r["cik"] != OUT_OF_COHORT_CIK]


def _write_worklist(path: Path, rows: list[dict]) -> Path:
    from pipeline.review_queue import PROVENANCE_WORKLIST_COLUMNS
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PROVENANCE_WORKLIST_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


def _stub_review_bundle(bundle_dir: Path, review_id: str) -> Path:
    """Write a minimal bundle JSON so bundle-ensure does not call build_review_bundles."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    p = bundle_dir / f"{review_id}.json"
    p.write_text(json.dumps({"review_id": review_id}), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# (a) Out-of-cohort rows are refused (exit 1)
# ---------------------------------------------------------------------------


def test_out_of_cohort_refused(tmp_path, monkeypatch):
    """build_batch with a mixed worklist (cohort + OOC) should raise SystemExit(1)."""
    import pipeline.cohort_guard as cg
    monkeypatch.setattr(cg, "load_cohort_ciks", lambda *a, **kw: COHORT_CIKS)

    wl_path = _write_worklist(tmp_path / "worklist.csv", _WORKLIST_ROWS)
    batch_dir = tmp_path / "batch" / "test_ooc"
    batch_dir.mkdir(parents=True)

    with pytest.raises(SystemExit) as exc_info:
        build_dispatch.build_batch(
            worklist_rows=_WORKLIST_ROWS,
            batch_dir=batch_dir,
            bundles_dir=tmp_path / "review_bundles",
        )
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# (b) With cohort-only rows: batch dir contains worklist.csv + prompts + manifest
# ---------------------------------------------------------------------------


def test_batch_dir_layout(tmp_path, monkeypatch):
    """build_batch with cohort-only rows creates expected files."""
    import pipeline.cohort_guard as cg
    import pipeline.review_bundles as rb
    monkeypatch.setattr(cg, "load_cohort_ciks", lambda *a, **kw: COHORT_CIKS)
    monkeypatch.setattr(rb, "build_review_bundles", lambda **kw: {})

    bundles_dir = tmp_path / "review_bundles"
    for row in _COHORT_ONLY_ROWS:
        _stub_review_bundle(bundles_dir, row["review_id"])

    batch_dir = tmp_path / "batch" / "test_layout"
    batch_dir.mkdir(parents=True)

    result = build_dispatch.build_batch(
        worklist_rows=_COHORT_ONLY_ROWS,
        batch_dir=batch_dir,
        bundles_dir=bundles_dir,
    )

    # worklist.csv present
    assert (batch_dir / "worklist.csv").exists()

    # one prompt per review_id
    prompts_dir = batch_dir / "prompts"
    assert prompts_dir.is_dir()
    for row in _COHORT_ONLY_ROWS:
        assert (prompts_dir / f"{row['review_id']}.md").exists()

    # manifest.json present
    assert (batch_dir / "manifest.json").exists()
    # wave-stamped manifest present (manifest_w1.json)
    assert (batch_dir / "manifest_w1.json").exists()


# ---------------------------------------------------------------------------
# (c) Manifest has correct keys: dispatch_requires, grant_profile, rows shape,
#     NO corrections_dir
# ---------------------------------------------------------------------------


def test_manifest_keys(tmp_path, monkeypatch):
    """Manifest must have dispatch_requires, grant_profile, rows[], no corrections_dir."""
    import pipeline.cohort_guard as cg
    import pipeline.review_bundles as rb
    monkeypatch.setattr(cg, "load_cohort_ciks", lambda *a, **kw: COHORT_CIKS)
    monkeypatch.setattr(rb, "build_review_bundles", lambda **kw: {})

    bundles_dir = tmp_path / "review_bundles"
    for row in _COHORT_ONLY_ROWS:
        _stub_review_bundle(bundles_dir, row["review_id"])

    batch_dir = tmp_path / "batch" / "test_keys"
    batch_dir.mkdir(parents=True)

    build_dispatch.build_batch(
        worklist_rows=_COHORT_ONLY_ROWS,
        batch_dir=batch_dir,
        bundles_dir=bundles_dir,
    )

    manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["dispatch_requires"] == "admin_shell"
    assert manifest["grant_profile"] == "read_only_classifier"
    assert "corrections_dir" not in manifest, "corrections_dir must NOT appear in ledger classifier manifest"
    assert "batch_id" in manifest
    assert "created_at" in manifest
    assert "worker_python" in manifest
    assert "worker_read_dirs" in manifest
    assert "n_dispatch" in manifest
    assert isinstance(manifest["rows"], list)
    assert len(manifest["rows"]) == len(_COHORT_ONLY_ROWS)

    for r in manifest["rows"]:
        assert "review_id" in r
        assert "cik" in r
        assert "report_date" in r
        assert "reason_code" in r
        assert "prompt_path" in r
        assert "bundle_path" in r
        assert "verdict_path" in r
        assert "lock_key" in r


# ---------------------------------------------------------------------------
# (d) Prompt text contains verdict vocabulary and verdict_path
# ---------------------------------------------------------------------------


def test_prompt_content(tmp_path, monkeypatch):
    """Each prompt must contain the adjudication vocabulary and the verdict_path."""
    import pipeline.cohort_guard as cg
    import pipeline.review_bundles as rb
    from pipeline.ledger_error_verdict import ADJUDICATIONS
    monkeypatch.setattr(cg, "load_cohort_ciks", lambda *a, **kw: COHORT_CIKS)
    monkeypatch.setattr(rb, "build_review_bundles", lambda **kw: {})

    bundles_dir = tmp_path / "review_bundles"
    for row in _COHORT_ONLY_ROWS:
        _stub_review_bundle(bundles_dir, row["review_id"])

    batch_dir = tmp_path / "batch" / "test_prompt"
    batch_dir.mkdir(parents=True)

    build_dispatch.build_batch(
        worklist_rows=_COHORT_ONLY_ROWS,
        batch_dir=batch_dir,
        bundles_dir=bundles_dir,
    )

    manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))

    for row_meta in manifest["rows"]:
        prompt_text = Path(row_meta["prompt_path"]).read_text(encoding="utf-8")

        # All adjudication verdict values must appear in the prompt
        for adj in ADJUDICATIONS:
            assert adj in prompt_text, f"verdict vocabulary '{adj}' missing from prompt {row_meta['review_id']}"

        # The verdict_path must appear in the prompt
        verdict_path = row_meta["verdict_path"]
        assert verdict_path in prompt_text, (
            f"verdict_path '{verdict_path}' not found in prompt for {row_meta['review_id']}"
        )

        # Key prompt structural elements
        assert "read-only" in prompt_text.lower() or "never modify" in prompt_text.lower()
        assert "gate" in prompt_text.lower()
        assert "escalation" in prompt_text.lower()

        # Flag summary
        rid = row_meta["review_id"]
        assert row_meta["cik"] in prompt_text
        assert row_meta["report_date"] in prompt_text
        assert row_meta["reason_code"] in prompt_text


# ---------------------------------------------------------------------------
# (e) Bundle-ensure: build_review_bundles called only for missing review_ids
# ---------------------------------------------------------------------------


def test_bundle_ensure_only_missing(tmp_path, monkeypatch):
    """build_review_bundles should only be called for review_ids missing their bundle."""
    import pipeline.cohort_guard as cg
    import pipeline.review_bundles as rb

    monkeypatch.setattr(cg, "load_cohort_ciks", lambda *a, **kw: COHORT_CIKS)

    called_with: list[set] = []

    def fake_build_review_bundles(**kw):
        called_with.append(set(kw.get("review_ids") or set()))
        return {}

    monkeypatch.setattr(rb, "build_review_bundles", fake_build_review_bundles)

    bundles_dir = tmp_path / "review_bundles"
    # Only stub the first row's bundle -- second should be requested
    _stub_review_bundle(bundles_dir, _COHORT_ONLY_ROWS[0]["review_id"])

    batch_dir = tmp_path / "batch" / "test_ensure"
    batch_dir.mkdir(parents=True)

    build_dispatch.build_batch(
        worklist_rows=_COHORT_ONLY_ROWS,
        batch_dir=batch_dir,
        bundles_dir=bundles_dir,
    )

    # build_review_bundles should have been called (at least once) with the missing id
    missing_id = _COHORT_ONLY_ROWS[1]["review_id"]
    all_requested = set().union(*called_with) if called_with else set()
    assert missing_id in all_requested, (
        f"expected build_review_bundles to be called for missing bundle {missing_id!r}; "
        f"was called with {called_with!r}"
    )

    # The already-present bundle should NOT appear in any build_review_bundles call
    present_id = _COHORT_ONLY_ROWS[0]["review_id"]
    assert present_id not in all_requested, (
        f"build_review_bundles was called for already-present bundle {present_id!r}"
    )


# ---------------------------------------------------------------------------
# (f) worker_read_dirs includes the expected data paths
# ---------------------------------------------------------------------------


def test_worker_read_dirs_content(tmp_path, monkeypatch):
    """worker_read_dirs must include the read-only grant list paths."""
    import pipeline.cohort_guard as cg
    import pipeline.review_bundles as rb
    monkeypatch.setattr(cg, "load_cohort_ciks", lambda *a, **kw: COHORT_CIKS)
    monkeypatch.setattr(rb, "build_review_bundles", lambda **kw: {})

    bundles_dir = tmp_path / "review_bundles"
    for row in _COHORT_ONLY_ROWS:
        _stub_review_bundle(bundles_dir, row["review_id"])

    batch_dir = tmp_path / "batch" / "test_rrd"
    batch_dir.mkdir(parents=True)

    build_dispatch.build_batch(
        worklist_rows=_COHORT_ONLY_ROWS,
        batch_dir=batch_dir,
        bundles_dir=bundles_dir,
    )

    manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
    rrd = manifest["worker_read_dirs"]
    # Must be a list of strings
    assert isinstance(rrd, list)
    assert all(isinstance(x, str) for x in rrd)
    # Must contain the four expected grant dirs (as substrings of one entry each)
    rrd_joined = "\n".join(rrd)
    assert "review_bundles" in rrd_joined
    assert "provenance_ledger" in rrd_joined
    assert "private_markets_holdings" in rrd_joined
    assert "bdc_xbrl" in rrd_joined


# ---------------------------------------------------------------------------
# (g) drift_fingerprint and per-verdict requirements appear in prompt
# ---------------------------------------------------------------------------


def test_prompt_contains_per_verdict_requirements(tmp_path, monkeypatch):
    """Prompt must document drift_fingerprint, mechanism, culprit_citations, etc."""
    import pipeline.cohort_guard as cg
    import pipeline.review_bundles as rb
    monkeypatch.setattr(cg, "load_cohort_ciks", lambda *a, **kw: COHORT_CIKS)
    monkeypatch.setattr(rb, "build_review_bundles", lambda **kw: {})

    bundles_dir = tmp_path / "review_bundles"
    for row in _COHORT_ONLY_ROWS:
        _stub_review_bundle(bundles_dir, row["review_id"])

    batch_dir = tmp_path / "batch" / "test_pv_req"
    batch_dir.mkdir(parents=True)

    build_dispatch.build_batch(
        worklist_rows=_COHORT_ONLY_ROWS,
        batch_dir=batch_dir,
        bundles_dir=bundles_dir,
    )

    manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
    # Check the first prompt (sufficient)
    prompt_text = Path(manifest["rows"][0]["prompt_path"]).read_text(encoding="utf-8")

    # extraction_wrong / parser_drift -> mechanism required
    assert "mechanism" in prompt_text
    # parser_drift -> drift_fingerprint
    assert "drift_fingerprint" in prompt_text
    # culprit_citations shape
    assert "culprit_citations" in prompt_text
    # filer_error -> filer_error_basis
    assert "filer_error_basis" in prompt_text
    # false_flag -> false_flag_basis (canary hardening 2026-08-25)
    assert "false_flag_basis" in prompt_text
    # amended -> superseding_accession
    assert "superseding_accession" in prompt_text
    # ambiguous -> ambiguity_basis
    assert "ambiguity_basis" in prompt_text
    # escalation sibling convention
    assert ".escalation.json" in prompt_text
