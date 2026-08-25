"""Tests for pipeline/ledger_error_verdict.py -- TDD first.

Covers:
- Schema validation for every ADJUDICATIONS member (positive + negative).
- Re-derivation gate: matching citation passes, fabricated value refused,
  unknown row refused, missing ledger refused.
- validate_dir: coverage, duplicates, unknown ids, escalation sibling counts.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from pipeline.ledger_error_verdict import (
    ADJUDICATIONS,
    REQUIRED_KEYS,
    rederive_citations,
    validate_dir,
    validate_ledger_verdict,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _leaf(**kw):
    base = {
        "review_id": "RVQ_BLK_abc123def456",
        "verdict": "extraction_wrong",
        "confidence": 0.8,
        "mechanism": "wrong_concept_selected",
        "culprit_citations": [
            {
                "row_id": "ROW-aaaa",
                "field": "fair_value",
                "declared_raw": 1000.0,
                "instance_raw": 1000.0,
                "published": 990.0,
            }
        ],
    }
    return {**base, **kw}


def _ledger_df():
    return pd.DataFrame(
        [
            {
                "row_id": "ROW-aaaa",
                "field": "fair_value",
                "reason_code": "filing_mismatch",
                "declared_raw": 1000.0,
                "instance_raw": 1000.0,
                "published": 990.0,
                "cheap_status": "pass",
                "full_status": "published_mismatch",
                "cik": "0001287750",
                "report_date": "2025-12-31",
                "expected": 1000.0,
                "src_context_id": "ctx1",
            }
        ]
    )


# ---------------------------------------------------------------------------
# ADJUDICATIONS / REQUIRED_KEYS contract
# ---------------------------------------------------------------------------


class TestConstants:
    def test_adjudications_tuple(self):
        assert isinstance(ADJUDICATIONS, tuple)
        assert set(ADJUDICATIONS) == {
            "extraction_wrong",
            "parser_drift",
            "filer_error",
            "amended",
            "false_flag",
            "ambiguous",
        }

    def test_required_keys(self):
        assert set(REQUIRED_KEYS) >= {"review_id", "verdict", "confidence"}


# ---------------------------------------------------------------------------
# Schema validation -- TestSchema (from brief)
# ---------------------------------------------------------------------------


class TestSchema:
    # --- extraction_wrong ---------------------------------------------------

    def test_extraction_wrong_requires_mechanism_and_citation(self):
        assert validate_ledger_verdict(_leaf())["ok"]
        assert not validate_ledger_verdict(_leaf(mechanism=""))["ok"]
        assert not validate_ledger_verdict(_leaf(culprit_citations=[]))["ok"]

    def test_extraction_wrong_requires_nonempty_mechanism(self):
        assert not validate_ledger_verdict(_leaf(mechanism=None))["ok"]

    def test_extraction_wrong_citation_shape_required(self):
        # citation missing field -> error
        bad_cite = [{"row_id": "ROW-aaaa", "declared_raw": 1.0}]
        assert not validate_ledger_verdict(_leaf(culprit_citations=bad_cite))["ok"]

    def test_extraction_wrong_citation_shape_ok_with_none_numerics(self):
        # None values are permitted for declared_raw/instance_raw/published
        ok_cite = [{"row_id": "ROW-aaaa", "field": "fair_value",
                    "declared_raw": None, "instance_raw": None, "published": None}]
        assert validate_ledger_verdict(_leaf(culprit_citations=ok_cite))["ok"]

    # --- parser_drift -------------------------------------------------------

    def test_parser_drift_requires_fingerprint(self):
        leaf = _leaf(
            verdict="parser_drift",
            drift_fingerprint={
                "field": "interest_rate",
                "transform_code": "rate_x100",
                "affected_row_ids": ["ROW-aaaa"],
            },
        )
        assert validate_ledger_verdict(leaf)["ok"]
        assert not validate_ledger_verdict(_leaf(verdict="parser_drift"))["ok"]

    def test_parser_drift_fingerprint_needs_nonempty_affected_rows(self):
        leaf = _leaf(
            verdict="parser_drift",
            drift_fingerprint={
                "field": "interest_rate",
                "transform_code": "rate_x100",
                "affected_row_ids": [],  # empty list -> error
            },
        )
        assert not validate_ledger_verdict(leaf)["ok"]

    def test_parser_drift_fingerprint_field_required(self):
        leaf = _leaf(
            verdict="parser_drift",
            drift_fingerprint={
                "transform_code": "rate_x100",
                "affected_row_ids": ["ROW-aaaa"],
                # missing "field"
            },
        )
        assert not validate_ledger_verdict(leaf)["ok"]

    def test_parser_drift_still_needs_mechanism_and_citation(self):
        leaf = _leaf(
            verdict="parser_drift",
            drift_fingerprint={
                "field": "interest_rate",
                "transform_code": "rate_x100",
                "affected_row_ids": ["ROW-aaaa"],
            },
        )
        # mechanism cleared -> fail
        leaf2 = {**leaf, "mechanism": ""}
        assert not validate_ledger_verdict(leaf2)["ok"]

    # --- filer_error --------------------------------------------------------

    def test_filer_error_requires_basis_and_citation(self):
        leaf = _leaf(
            verdict="filer_error",
            filer_error_basis="Issuer reported wrong fair value in their schedule.",
        )
        assert validate_ledger_verdict(leaf)["ok"]

    def test_filer_error_missing_basis_fails(self):
        leaf = _leaf(verdict="filer_error")
        assert not validate_ledger_verdict(leaf)["ok"]

    def test_filer_error_empty_basis_fails(self):
        leaf = _leaf(verdict="filer_error", filer_error_basis="")
        assert not validate_ledger_verdict(leaf)["ok"]

    def test_filer_error_warns_when_escalate_not_true(self):
        leaf = _leaf(
            verdict="filer_error",
            filer_error_basis="Bad filer",
            escalate=False,
        )
        result = validate_ledger_verdict(leaf)
        assert result["ok"]  # warn only, not error
        assert any("escalate" in w for w in result["warnings"])

    def test_filer_error_no_warning_when_escalate_true(self):
        leaf = _leaf(
            verdict="filer_error",
            filer_error_basis="Bad filer",
            escalate=True,
        )
        result = validate_ledger_verdict(leaf)
        assert result["ok"]
        assert not any("escalate" in w for w in result["warnings"])

    # --- amended ------------------------------------------------------------

    def test_amended_requires_superseding_accession(self):
        ok = _leaf(verdict="amended", superseding_accession="0001-26-000009")
        assert validate_ledger_verdict(ok)["ok"]
        assert not validate_ledger_verdict(_leaf(verdict="amended"))["ok"]

    def test_amended_empty_accession_fails(self):
        assert not validate_ledger_verdict(
            _leaf(verdict="amended", superseding_accession="")
        )["ok"]

    def test_amended_no_citations_required(self):
        # amended does not need culprit_citations
        ok = _leaf(
            verdict="amended",
            superseding_accession="0001-26-000009",
            culprit_citations=[],
        )
        assert validate_ledger_verdict(ok)["ok"]

    # --- false_flag ---------------------------------------------------------
    # Canary 2026-08-25: a worker chose false_flag explicitly because it required
    # no evidence. false_flag now requires a basis AND >=1 citation so the claim
    # "this flag is spurious" is itself re-derivable at the gate.

    def test_false_flag_requires_basis_and_citation(self):
        ok = _leaf(
            verdict="false_flag",
            false_flag_basis="Published pct is recomputed FV/NAV; declared is the rounded fraction x100 -- comparison artifact.",
        )
        assert validate_ledger_verdict(ok)["ok"]

    def test_false_flag_bare_leaf_fails(self):
        leaf = {"review_id": "RVQ_BLK_ff1", "verdict": "false_flag", "confidence": 0.9}
        assert not validate_ledger_verdict(leaf)["ok"]

    def test_false_flag_empty_basis_fails(self):
        leaf = _leaf(verdict="false_flag", false_flag_basis="")
        assert not validate_ledger_verdict(leaf)["ok"]

    def test_false_flag_missing_citations_fails(self):
        leaf = _leaf(
            verdict="false_flag",
            false_flag_basis="Comparison artifact.",
            culprit_citations=[],
        )
        assert not validate_ledger_verdict(leaf)["ok"]

    # --- ambiguous ----------------------------------------------------------

    def test_ambiguous_requires_ambiguity_basis(self):
        leaf = {"review_id": "RVQ_BLK_amb1", "verdict": "ambiguous", "confidence": 0.5}
        assert not validate_ledger_verdict(leaf)["ok"]

    def test_ambiguous_evidence_insufficient_passes(self):
        leaf = {
            "review_id": "RVQ_BLK_amb2",
            "verdict": "ambiguous",
            "confidence": 0.5,
            "ambiguity_basis": "evidence_insufficient",
        }
        assert validate_ledger_verdict(leaf)["ok"]

    def test_ambiguous_source_unavailable_warns_no_escalate(self):
        leaf = {
            "review_id": "RVQ_BLK_amb3",
            "verdict": "ambiguous",
            "confidence": 0.5,
            "ambiguity_basis": "source_unavailable",
        }
        result = validate_ledger_verdict(leaf)
        assert result["ok"]
        assert any("escalate" in w for w in result["warnings"])

    def test_ambiguous_source_unavailable_no_warning_with_escalate(self):
        leaf = {
            "review_id": "RVQ_BLK_amb4",
            "verdict": "ambiguous",
            "confidence": 0.5,
            "ambiguity_basis": "source_unavailable",
            "escalate": True,
        }
        result = validate_ledger_verdict(leaf)
        assert result["ok"]
        assert not any("escalate" in w for w in result["warnings"])

    def test_ambiguous_invalid_basis_fails(self):
        leaf = {
            "review_id": "RVQ_BLK_amb5",
            "verdict": "ambiguous",
            "confidence": 0.5,
            "ambiguity_basis": "made_up_reason",
        }
        assert not validate_ledger_verdict(leaf)["ok"]

    # --- confidence ---------------------------------------------------------

    def test_confidence_out_of_range_fails(self):
        assert not validate_ledger_verdict(_leaf(confidence=1.5))["ok"]
        assert not validate_ledger_verdict(_leaf(confidence=-0.1))["ok"]

    def test_confidence_boundaries_ok(self):
        assert validate_ledger_verdict(_leaf(confidence=0.0))["ok"]
        assert validate_ledger_verdict(_leaf(confidence=1.0))["ok"]

    # --- unknown verdict ----------------------------------------------------

    def test_unknown_verdict_fails(self):
        assert not validate_ledger_verdict(_leaf(verdict="made_up"))["ok"]

    # --- missing required keys ----------------------------------------------

    def test_missing_review_id_fails(self):
        d = _leaf()
        del d["review_id"]
        assert not validate_ledger_verdict(d)["ok"]

    def test_missing_confidence_fails(self):
        d = _leaf()
        del d["confidence"]
        assert not validate_ledger_verdict(d)["ok"]


# ---------------------------------------------------------------------------
# Re-derivation gate -- TestRederivation (from brief + symmetric negatives)
# ---------------------------------------------------------------------------


class TestRederivation:
    def test_matching_citation_passes(self):
        assert rederive_citations(_leaf(), ledger_df=_ledger_df())["ok"]

    def test_fabricated_value_refused(self):
        bad = _leaf()
        bad["culprit_citations"][0]["instance_raw"] = 555.0
        out = rederive_citations(bad, ledger_df=_ledger_df())
        assert not out["ok"] and "instance_raw" in str(out["errors"])

    def test_unknown_row_refused(self):
        bad = _leaf()
        bad["culprit_citations"][0]["row_id"] = "ROW-zzzz"
        assert not rederive_citations(bad, ledger_df=_ledger_df())["ok"]

    def test_missing_ledger_file_refused(self, tmp_path):
        # ledger_path pointing at non-existent file -> fail-closed, not silently pass
        result = rederive_citations(_leaf(), ledger_path=tmp_path / "nonexistent.csv")
        assert not result["ok"]
        assert result["errors"]

    def test_reason_code_not_tight_refused(self):
        df = _ledger_df().copy()
        df.at[0, "reason_code"] = "verified"  # a pass code, not a tight fail code
        out = rederive_citations(_leaf(), ledger_df=df)
        assert not out["ok"]
        assert any("reason_code" in e for e in out["errors"])

    def test_none_matches_null_in_ledger(self):
        # declared_raw=None in citation should match NULL (NaN) in ledger
        df = _ledger_df().copy()
        df.at[0, "declared_raw"] = float("nan")
        leaf = _leaf()
        leaf["culprit_citations"][0]["declared_raw"] = None
        assert rederive_citations(leaf, ledger_df=df)["ok"]

    def test_published_mismatch_refused(self):
        bad = _leaf()
        bad["culprit_citations"][0]["published"] = 12345.0
        out = rederive_citations(bad, ledger_df=_ledger_df())
        assert not out["ok"]
        assert "published" in str(out["errors"])

    def test_declared_raw_mismatch_refused(self):
        bad = _leaf()
        bad["culprit_citations"][0]["declared_raw"] = 9999.0
        out = rederive_citations(bad, ledger_df=_ledger_df())
        assert not out["ok"]
        assert "declared_raw" in str(out["errors"])

    def test_no_citations_skips_gate(self):
        # verdicts without culprit_citations (e.g. amended) pass the gate trivially
        # (schema-level citation requirements are validate_ledger_verdict's job)
        leaf = {
            "review_id": "RVQ_BLK_x",
            "verdict": "amended",
            "confidence": 0.9,
            "superseding_accession": "0001-26-000009",
        }
        assert rederive_citations(leaf, ledger_df=_ledger_df())["ok"]

    def test_near_equal_passes_within_reltol(self):
        # Values within rel-tol 1e-9 should pass
        df = _ledger_df().copy()
        df.at[0, "published"] = 990.0 * (1 + 1e-10)
        leaf = _leaf()
        leaf["culprit_citations"][0]["published"] = 990.0
        assert rederive_citations(leaf, ledger_df=df)["ok"]

    def test_wrong_field_refused(self):
        # Citation field mismatch: row exists but under different field
        leaf = _leaf()
        leaf["culprit_citations"][0]["field"] = "interest_rate"  # not in ledger
        out = rederive_citations(leaf, ledger_df=_ledger_df())
        assert not out["ok"]


# ---------------------------------------------------------------------------
# validate_dir
# ---------------------------------------------------------------------------


class TestValidateDir:
    def _write_leaf(self, dirpath: Path, review_id: str, **kw):
        leaf = {**_leaf(**kw), "review_id": review_id}
        (dirpath / f"{review_id}.json").write_text(json.dumps(leaf), encoding="utf-8")

    def _write_simple_leaf(self, dirpath: Path, review_id: str):
        """Write an amended leaf (no citations -> gate trivially passes)."""
        leaf = {
            "review_id": review_id,
            "verdict": "amended",
            "confidence": 0.9,
            "superseding_accession": "0001-26-000009",
        }
        (dirpath / f"{review_id}.json").write_text(json.dumps(leaf), encoding="utf-8")

    def _write_worklist(self, dirpath: Path, review_ids: list[str]) -> Path:
        wl = dirpath / "worklist.csv"
        wl.write_text("review_id\n" + "\n".join(review_ids), encoding="utf-8")
        return wl

    def test_all_valid_passes(self, tmp_path):
        vd = tmp_path / "verdicts"
        vd.mkdir()
        # Use a leaf with citations -- inject ledger_df so gate can verify them
        leaf = {**_leaf(), "review_id": "RVQ_BLK_aaa"}
        (vd / "RVQ_BLK_aaa.json").write_text(json.dumps(leaf), encoding="utf-8")
        wl = self._write_worklist(tmp_path, ["RVQ_BLK_aaa"])
        result = validate_dir(vd, wl, ledger_df=_ledger_df())
        assert result["ok"], result
        assert result["n_valid"] == 1

    def test_all_valid_passes_no_citations(self, tmp_path):
        """false_flag leaf needs no ledger injection."""
        vd = tmp_path / "verdicts"
        vd.mkdir()
        self._write_simple_leaf(vd, "RVQ_BLK_aaa2")
        wl = self._write_worklist(tmp_path, ["RVQ_BLK_aaa2"])
        result = validate_dir(vd, wl)
        assert result["ok"]
        assert result["n_valid"] == 1

    def test_missing_verdict_fails(self, tmp_path):
        vd = tmp_path / "verdicts"
        vd.mkdir()
        wl = self._write_worklist(tmp_path, ["RVQ_BLK_missing"])
        result = validate_dir(vd, wl)
        assert not result["ok"]
        assert any("missing" in e for e in result["cross_errors"])

    def test_duplicate_review_id_fails(self, tmp_path):
        vd = tmp_path / "verdicts"
        vd.mkdir()
        # Write two files with same review_id but different filenames
        leaf = {**_leaf(), "review_id": "RVQ_BLK_dup"}
        (vd / "RVQ_BLK_dup.json").write_text(json.dumps(leaf), encoding="utf-8")
        (vd / "RVQ_BLK_dup_b.json").write_text(json.dumps(leaf), encoding="utf-8")
        wl = self._write_worklist(tmp_path, ["RVQ_BLK_dup"])
        result = validate_dir(vd, wl, ledger_df=_ledger_df())
        assert not result["ok"]
        assert any("duplicate" in e for e in result["cross_errors"])

    def test_unknown_review_id_fails(self, tmp_path):
        vd = tmp_path / "verdicts"
        vd.mkdir()
        self._write_simple_leaf(vd, "RVQ_BLK_unknown")
        wl = self._write_worklist(tmp_path, ["RVQ_BLK_other"])
        result = validate_dir(vd, wl)
        assert not result["ok"]

    def test_escalation_sibling_counts_as_coverage(self, tmp_path):
        vd = tmp_path / "verdicts"
        vd.mkdir()
        # Only escalation file, no verdict file
        esc = vd / "RVQ_BLK_esc.escalation.json"
        esc.write_text(json.dumps({"review_id": "RVQ_BLK_esc", "escalated": True}), encoding="utf-8")
        wl = self._write_worklist(tmp_path, ["RVQ_BLK_esc"])
        result = validate_dir(vd, wl)
        assert result["ok"], result

    def test_invalid_schema_in_dir_fails(self, tmp_path):
        vd = tmp_path / "verdicts"
        vd.mkdir()
        leaf = {**_leaf(), "review_id": "RVQ_BLK_bad", "confidence": 5.0}  # invalid conf
        (vd / "RVQ_BLK_bad.json").write_text(json.dumps(leaf), encoding="utf-8")
        wl = self._write_worklist(tmp_path, ["RVQ_BLK_bad"])
        result = validate_dir(vd, wl, ledger_df=_ledger_df())
        assert not result["ok"]

    def test_invalid_gate_in_dir_fails(self, tmp_path):
        """Re-derivation failure (fabricated citation value) counts as invalid."""
        vd = tmp_path / "verdicts"
        vd.mkdir()
        bad = _leaf()
        bad["culprit_citations"][0]["instance_raw"] = 555.0
        bad["review_id"] = "RVQ_BLK_gate_bad"
        (vd / "RVQ_BLK_gate_bad.json").write_text(json.dumps(bad), encoding="utf-8")
        wl = self._write_worklist(tmp_path, ["RVQ_BLK_gate_bad"])
        result = validate_dir(vd, wl, ledger_df=_ledger_df())
        assert not result["ok"]

    def test_unreadable_json_fails(self, tmp_path):
        vd = tmp_path / "verdicts"
        vd.mkdir()
        (vd / "RVQ_BLK_corrupt.json").write_text("not valid json", encoding="utf-8")
        wl = self._write_worklist(tmp_path, ["RVQ_BLK_corrupt"])
        result = validate_dir(vd, wl)
        assert not result["ok"]


# ---------------------------------------------------------------------------
# Tight-codes import equality assertion
# ---------------------------------------------------------------------------


def test_tight_codes_match_shadow_adapter():
    """Local PROV_TIGHT_FAIL copy must equal scripts.shadow_adapter.PROV_TIGHT_FAIL."""
    import sys
    import importlib
    from pathlib import Path as _Path

    repo_root = _Path(__file__).resolve().parent.parent
    scripts_dir = str(repo_root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        sa = importlib.import_module("shadow_adapter")
    except ImportError:
        pytest.fail("shadow_adapter not importable -- check sys.path injection")
    from pipeline.ledger_error_verdict import _PROV_TIGHT_FAIL_LOCAL
    assert _PROV_TIGHT_FAIL_LOCAL == sa.PROV_TIGHT_FAIL, (
        f"Local copy diverges from shadow_adapter: "
        f"local={_PROV_TIGHT_FAIL_LOCAL}, adapter={sa.PROV_TIGHT_FAIL}"
    )


# ---------------------------------------------------------------------------
# Finding 1: duplicate (row_id, field) ledger rows -- ambiguous evidence
# ---------------------------------------------------------------------------


def _ledger_df_dup_agree():
    """Two rows with same (row_id, field) that agree on all cited columns."""
    return pd.DataFrame([
        {
            "row_id": "ROW-aaaa", "field": "fair_value", "reason_code": "filing_mismatch",
            "declared_raw": 1000.0, "instance_raw": 1000.0, "published": 990.0,
            "cheap_status": "pass", "full_status": "published_mismatch",
            "cik": "0001287750", "report_date": "2025-12-31",
            "expected": 1000.0, "src_context_id": "ctx1",
        },
        {
            "row_id": "ROW-aaaa", "field": "fair_value", "reason_code": "filing_mismatch",
            "declared_raw": 1000.0, "instance_raw": 1000.0, "published": 990.0,
            "cheap_status": "pass", "full_status": "published_mismatch",
            "cik": "0001287750", "report_date": "2025-12-31",
            "expected": 1000.0, "src_context_id": "ctx2",  # non-cited col differs -- ok
        },
    ])


def _ledger_df_dup_differ():
    """Two rows with same (row_id, field) that DIFFER on instance_raw."""
    return pd.DataFrame([
        {
            "row_id": "ROW-aaaa", "field": "fair_value", "reason_code": "filing_mismatch",
            "declared_raw": 1000.0, "instance_raw": 1000.0, "published": 990.0,
            "cheap_status": "pass", "full_status": "published_mismatch",
            "cik": "0001287750", "report_date": "2025-12-31",
            "expected": 1000.0, "src_context_id": "ctx1",
        },
        {
            "row_id": "ROW-aaaa", "field": "fair_value", "reason_code": "filing_mismatch",
            "declared_raw": 1000.0, "instance_raw": 999.0,  # DIFFERS
            "published": 990.0,
            "cheap_status": "pass", "full_status": "published_mismatch",
            "cik": "0001287750", "report_date": "2025-12-31",
            "expected": 1000.0, "src_context_id": "ctx2",
        },
    ])


class TestDuplicateLedgerRows:
    """Finding 1: duplicate (row_id, field) rows must be handled deterministically."""

    def test_duplicate_rows_agreeing_passes(self):
        """Duplicate rows that agree on all cited numeric columns -> pass."""
        out = rederive_citations(_leaf(), ledger_df=_ledger_df_dup_agree())
        assert out["ok"], out["errors"]

    def test_duplicate_rows_differing_refused_with_ambiguous_error(self):
        """Duplicate rows with differing instance_raw -> refused with ambiguous/duplicate error."""
        out = rederive_citations(_leaf(), ledger_df=_ledger_df_dup_differ())
        assert not out["ok"]
        err_text = " ".join(out["errors"]).lower()
        assert "ambiguous" in err_text or "duplicate" in err_text

    def test_duplicate_rows_differing_error_names_field(self):
        """The ambiguous-evidence error message must identify the conflicting field."""
        out = rederive_citations(_leaf(), ledger_df=_ledger_df_dup_differ())
        assert not out["ok"]
        assert any("instance_raw" in e or "fair_value" in e for e in out["errors"])

    def test_duplicate_via_duckdb_path_agree_passes(self, tmp_path):
        """Same duplicate-agree semantics via the DuckDB path (small tmp_path CSV)."""
        import csv as _csv
        ledger_csv = tmp_path / "ledger.csv"
        cols = ["row_id", "field", "reason_code", "declared_raw", "instance_raw", "published",
                "cik", "report_date"]
        rows = [
            ["ROW-aaaa", "fair_value", "filing_mismatch", "1000.0", "1000.0", "990.0",
             "0001287750", "2025-12-31"],
            ["ROW-aaaa", "fair_value", "filing_mismatch", "1000.0", "1000.0", "990.0",
             "0001287750", "2025-12-31"],
        ]
        with ledger_csv.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        out = rederive_citations(_leaf(), ledger_path=ledger_csv)
        assert out["ok"], out["errors"]

    def test_duplicate_via_duckdb_path_differ_refused(self, tmp_path):
        """Duplicate-differ semantics via DuckDB path -> refused with ambiguous/duplicate error."""
        import csv as _csv
        ledger_csv = tmp_path / "ledger.csv"
        cols = ["row_id", "field", "reason_code", "declared_raw", "instance_raw", "published",
                "cik", "report_date"]
        rows = [
            ["ROW-aaaa", "fair_value", "filing_mismatch", "1000.0", "1000.0", "990.0",
             "0001287750", "2025-12-31"],
            ["ROW-aaaa", "fair_value", "filing_mismatch", "1000.0", "999.0", "990.0",
             "0001287750", "2025-12-31"],
        ]
        with ledger_csv.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        out = rederive_citations(_leaf(), ledger_path=ledger_csv)
        assert not out["ok"]
        err_text = " ".join(out["errors"]).lower()
        assert "ambiguous" in err_text or "duplicate" in err_text


# ---------------------------------------------------------------------------
# Finding 3: DuckDB path uses filtered read (not full-table scan)
# ---------------------------------------------------------------------------


class TestDataFrameFilteredRead:
    """Finding 2: _build_ledger_lookup ledger_df path must pre-filter to cited pairs
    before calling _df_to_lookup, so duplicate-detection runs only on cited pairs.

    Uncited duplicates with differing values should NOT generate ambiguous errors
    that block otherwise valid citations.
    """

    def test_ledger_df_cited_only_ignores_uncited_duplicates(self):
        """ledger_df containing an uncited duplicate pair (differing values) must not
        cause re-derivation to fail when only the cited row ROW-aaaa is cited.

        Scenario:
        - ledger_df has ROW-aaaa/fair_value once (cited)
        - ledger_df has ROW-bbbb/cost twice with DIFFERING values (uncited)
        - Leaf cites only ROW-aaaa/fair_value

        Expected: ok=True, no errors. The uncited duplicate mismatch is irrelevant.
        Current (broken): ambiguous error from uncited ROW-bbbb/cost pair blocks the gate.
        """
        df = pd.DataFrame([
            # Cited: ROW-aaaa/fair_value once
            {
                "row_id": "ROW-aaaa", "field": "fair_value",
                "reason_code": "filing_mismatch",
                "declared_raw": 1000.0, "instance_raw": 1000.0, "published": 990.0,
                "cheap_status": "pass", "full_status": "published_mismatch",
                "cik": "0001287750", "report_date": "2025-12-31",
                "expected": 1000.0, "src_context_id": "ctx1",
            },
            # Uncited: ROW-bbbb/cost row 1
            {
                "row_id": "ROW-bbbb", "field": "cost",
                "reason_code": "filing_mismatch",
                "declared_raw": 500.0, "instance_raw": 500.0, "published": 500.0,
                "cheap_status": "pass", "full_status": "pass",
                "cik": "0001287750", "report_date": "2025-12-31",
                "expected": 500.0, "src_context_id": "ctx1",
            },
            # Uncited: ROW-bbbb/cost row 2 (same row_id/field, DIFFERING published)
            {
                "row_id": "ROW-bbbb", "field": "cost",
                "reason_code": "filing_mismatch",
                "declared_raw": 500.0, "instance_raw": 500.0, "published": 510.0,  # DIFFERS
                "cheap_status": "pass", "full_status": "pass",
                "cik": "0001287750", "report_date": "2025-12-31",
                "expected": 500.0, "src_context_id": "ctx2",
            },
        ])
        # Leaf only cites ROW-aaaa
        leaf = _leaf()
        out = rederive_citations(leaf, ledger_df=df)
        assert out["ok"], f"Expected ok=True, but got errors: {out['errors']}"


class TestDuckDBFilteredRead:
    """Finding 3: _duckdb_lookup must apply a WHERE clause restricting to cited pairs."""

    def test_duckdb_reads_only_cited_rows(self, tmp_path, monkeypatch):
        """The DuckDB lookup must NOT read rows for (row_id, field) pairs not cited.

        We verify this by placing a row with a BAD reason_code for an uncited pair;
        if the implementation fetches all rows and builds a lookup, the bad row would
        be a key in the dict but would not cause a gate failure (it's not cited).
        The test specifically confirms the cited row IS validated correctly.
        A separate test checks that a full-table read + iterrows is replaced by
        a vectorized dict build (we verify via the absence of iterrows in the impl).
        """
        import csv as _csv
        ledger_csv = tmp_path / "ledger.csv"
        cols = ["row_id", "field", "reason_code", "declared_raw", "instance_raw", "published",
                "cik", "report_date"]
        rows = [
            # cited row -- correct
            ["ROW-aaaa", "fair_value", "filing_mismatch", "1000.0", "1000.0", "990.0",
             "0001287750", "2025-12-31"],
            # uncited row with bad reason_code -- should be irrelevant
            ["ROW-bbbb", "interest_rate", "verified", "5.0", "5.0", "5.0",
             "0001287750", "2025-12-31"],
        ]
        with ledger_csv.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        # Only ROW-aaaa/fair_value is cited; gate should pass
        out = rederive_citations(_leaf(), ledger_path=ledger_csv)
        assert out["ok"], out["errors"]

    def test_no_iterrows_in_implementation(self):
        """Implementation must not use iterrows -- contract from AGENTS.md no-iterrows rule."""
        import inspect
        from pipeline import ledger_error_verdict
        src = inspect.getsource(ledger_error_verdict)
        assert "iterrows" not in src, (
            "_df_to_lookup or _duckdb_lookup still uses iterrows; replace with vectorized dict build"
        )


# ---------------------------------------------------------------------------
# End-to-end validate_dir gate proof (Task 4 -- no canary substitute)
#
# Three review_ids in a 2-row worklist + 1 escalation:
#   RVQ_BLK_e2e_valid    -- valid extraction_wrong verdict, citations reproduce -> ACCEPTED
#   RVQ_BLK_e2e_fab      -- fabricated instance_raw in citation -> gate REFUSES
#   RVQ_BLK_e2e_esc      -- escalation sibling only (no verdict file) -> counts as coverage
#
# Gate proof contract:
#   - validate_dir overall ok=False (one fabricated citation blocked)
#   - RVQ_BLK_e2e_valid ok=True (n_valid == 1)
#   - RVQ_BLK_e2e_fab ok=False (n_invalid == 1)
#   - RVQ_BLK_e2e_esc covered by escalation sibling (no missing-verdict cross_error)
# ---------------------------------------------------------------------------


def _e2e_ledger_df():
    """Two-row ledger that covers both the valid and fabricated review items."""
    return pd.DataFrame([
        {
            "row_id": "ROW-e2e1",
            "field": "fair_value",
            "reason_code": "filing_mismatch",
            "declared_raw": 2000.0,
            "instance_raw": 2000.0,
            "published": 1950.0,
            "cheap_status": "pass",
            "full_status": "published_mismatch",
            "cik": "0001803498",
            "report_date": "2025-09-30",
            "expected": 2000.0,
            "src_context_id": "ctx_e2e",
        },
        {
            "row_id": "ROW-e2e2",
            "field": "fair_value",
            "reason_code": "filing_mismatch",
            "declared_raw": 3000.0,
            "instance_raw": 3000.0,
            "published": 2900.0,
            "cheap_status": "pass",
            "full_status": "published_mismatch",
            "cik": "0001803498",
            "report_date": "2025-06-30",
            "expected": 3000.0,
            "src_context_id": "ctx_e2e2",
        },
    ])


class TestEndToEndValidateDir:
    """Gate proof: valid verdict ACCEPTED, fabricated citation REFUSED,
    escalation sibling satisfies coverage -- all via validate_dir fixture call.

    No workers are dispatched; this is the hand-authored no-canary substitute.
    """

    def _write_verdict(self, dirpath: Path, review_id: str, leaf: dict) -> None:
        (dirpath / f"{review_id}.json").write_text(
            json.dumps({**leaf, "review_id": review_id}), encoding="utf-8"
        )

    def _write_escalation(self, dirpath: Path, review_id: str) -> None:
        esc = {
            "review_id": review_id,
            "ambiguity_basis": "source_unavailable",
            "escalation_reason": "Source filing not yet cached; cannot verify citation.",
            "confidence": 0.1,
        }
        (dirpath / f"{review_id}.escalation.json").write_text(
            json.dumps(esc), encoding="utf-8"
        )

    def _write_worklist(self, dirpath: Path, review_ids: list[str]) -> Path:
        wl = dirpath / "worklist.csv"
        wl.write_text("review_id\n" + "\n".join(review_ids), encoding="utf-8")
        return wl

    def test_end_to_end_gate_proof(self, tmp_path):
        """Full e2e: valid ACCEPTED, fabricated citation REFUSED, escalation covers."""
        vd = tmp_path / "verdicts"
        vd.mkdir()

        # (1) Valid verdict: citations exactly match the fixture ledger
        valid_leaf = {
            "verdict": "extraction_wrong",
            "confidence": 0.9,
            "mechanism": "xbrl_concept_mismatch",
            "culprit_citations": [
                {
                    "row_id": "ROW-e2e1",
                    "field": "fair_value",
                    "declared_raw": 2000.0,
                    "instance_raw": 2000.0,
                    "published": 1950.0,
                }
            ],
        }
        self._write_verdict(vd, "RVQ_BLK_e2e_valid", valid_leaf)

        # (2) Fabricated citation: instance_raw 555.0 does not match ledger 3000.0
        fabricated_leaf = {
            "verdict": "extraction_wrong",
            "confidence": 0.8,
            "mechanism": "wrong_scale_applied",
            "culprit_citations": [
                {
                    "row_id": "ROW-e2e2",
                    "field": "fair_value",
                    "declared_raw": 3000.0,
                    "instance_raw": 555.0,   # fabricated -- ledger has 3000.0
                    "published": 2900.0,
                }
            ],
        }
        self._write_verdict(vd, "RVQ_BLK_e2e_fab", fabricated_leaf)

        # (3) Escalation sibling -- no verdict file; counts as coverage
        self._write_escalation(vd, "RVQ_BLK_e2e_esc")

        # Worklist covers all three review_ids
        wl = self._write_worklist(tmp_path, [
            "RVQ_BLK_e2e_valid",
            "RVQ_BLK_e2e_fab",
            "RVQ_BLK_e2e_esc",
        ])

        result = validate_dir(vd, wl, ledger_df=_e2e_ledger_df())

        # Overall: NOT ok (fabricated citation causes failure)
        assert not result["ok"], (
            "validate_dir should be not-ok when one verdict has a fabricated citation"
        )

        # n_valid == 1 (the valid leaf passed both schema and gate)
        assert result["n_valid"] == 1, f"Expected n_valid=1, got {result['n_valid']}"

        # n_error_files == 1 (the fabricated-citation leaf failed the gate)
        assert result["n_error_files"] == 1, (
            f"Expected n_error_files=1, got {result['n_error_files']}"
        )

        # No missing-verdict cross_error for the escalation sibling
        cross_err_text = " ".join(result.get("cross_errors", []))
        assert "RVQ_BLK_e2e_esc" not in cross_err_text, (
            "Escalation sibling should satisfy coverage; 'missing' error should not name it"
        )

        # The fabricated-citation leaf should appear in per_file as not-ok
        per_file_map = {pf["review_id"]: pf for pf in result.get("per_file", [])}
        assert "RVQ_BLK_e2e_valid" in per_file_map
        assert per_file_map["RVQ_BLK_e2e_valid"]["ok"] is True, (
            "Valid leaf should pass both schema and gate"
        )
        assert "RVQ_BLK_e2e_fab" in per_file_map
        assert per_file_map["RVQ_BLK_e2e_fab"]["ok"] is False, (
            "Fabricated-citation leaf should fail at the re-derivation gate"
        )
        fab_errors = per_file_map["RVQ_BLK_e2e_fab"]["errors"]
        assert any("instance_raw" in e for e in fab_errors), (
            f"Gate error should identify 'instance_raw' as the fabricated field; got {fab_errors}"
        )


# ---------------------------------------------------------------------------
# Finding 1: packet-scope binding
# ---------------------------------------------------------------------------


def _ledger_df_two_ciks():
    """Ledger with two rows: ROW-aaaa belongs to CIK-A, ROW-bbbb belongs to CIK-B."""
    return pd.DataFrame([
        {
            "row_id": "ROW-aaaa",
            "field": "fair_value",
            "reason_code": "filing_mismatch",
            "declared_raw": 1000.0,
            "instance_raw": 1000.0,
            "published": 990.0,
            "cheap_status": "pass",
            "full_status": "published_mismatch",
            "cik": "0001287750",
            "report_date": "2025-12-31",
            "expected": 1000.0,
            "src_context_id": "ctx1",
        },
        {
            "row_id": "ROW-bbbb",
            "field": "fair_value",
            "reason_code": "filing_mismatch",
            "declared_raw": 2000.0,
            "instance_raw": 2000.0,
            "published": 1980.0,
            "cheap_status": "pass",
            "full_status": "published_mismatch",
            "cik": "0001803498",  # different CIK
            "report_date": "2025-12-31",
            "expected": 2000.0,
            "src_context_id": "ctx2",
        },
    ])


class TestPacketScopeBinding:
    """Finding 1: citations must belong to the packet's (cik, report_date)."""

    def test_same_packet_citation_accepted(self):
        """Citation from the correct cik+report_date is accepted."""
        leaf = _leaf()  # cites ROW-aaaa which belongs to 0001287750 / 2025-12-31
        packet = {"cik": "0001287750", "report_date": "2025-12-31"}
        out = rederive_citations(leaf, ledger_df=_ledger_df_two_ciks(), packet=packet)
        assert out["ok"], out["errors"]

    def test_cross_cik_citation_refused(self):
        """Row exists and values match, but it belongs to a different CIK -- refused."""
        # Build a leaf that cites ROW-bbbb (which exists in the ledger but belongs to
        # CIK 0001803498) while the packet declares CIK 0001287750.
        leaf = {
            "review_id": "RVQ_BLK_scope_test",
            "verdict": "extraction_wrong",
            "confidence": 0.8,
            "mechanism": "wrong_concept",
            "culprit_citations": [
                {
                    "row_id": "ROW-bbbb",
                    "field": "fair_value",
                    "declared_raw": 2000.0,
                    "instance_raw": 2000.0,
                    "published": 1980.0,
                }
            ],
        }
        packet = {"cik": "0001287750", "report_date": "2025-12-31"}
        out = rederive_citations(leaf, ledger_df=_ledger_df_two_ciks(), packet=packet)
        assert not out["ok"]
        err_text = " ".join(out["errors"])
        assert "packet scope" in err_text or "outside packet" in err_text

    def test_no_packet_skips_scope_check(self):
        """When packet is None, no scope check is run -- cross-CIK row is accepted."""
        leaf = {
            "review_id": "RVQ_BLK_scope_test2",
            "verdict": "extraction_wrong",
            "confidence": 0.8,
            "mechanism": "wrong_concept",
            "culprit_citations": [
                {
                    "row_id": "ROW-bbbb",
                    "field": "fair_value",
                    "declared_raw": 2000.0,
                    "instance_raw": 2000.0,
                    "published": 1980.0,
                }
            ],
        }
        out = rederive_citations(leaf, ledger_df=_ledger_df_two_ciks(), packet=None)
        assert out["ok"], out["errors"]

    def test_validate_dir_cross_packet_citation_refused(self, tmp_path):
        """validate_dir enforces scope: a verdict citing a row from another CIK is refused."""
        vd = tmp_path / "verdicts"
        vd.mkdir()
        # Leaf cites ROW-bbbb (CIK 0001803498) but worklist says this is CIK 0001287750
        leaf = {
            "review_id": "RVQ_BLK_scope_dir",
            "verdict": "extraction_wrong",
            "confidence": 0.8,
            "mechanism": "wrong_concept",
            "culprit_citations": [
                {
                    "row_id": "ROW-bbbb",
                    "field": "fair_value",
                    "declared_raw": 2000.0,
                    "instance_raw": 2000.0,
                    "published": 1980.0,
                }
            ],
        }
        (vd / "RVQ_BLK_scope_dir.json").write_text(json.dumps(leaf), encoding="utf-8")
        wl = tmp_path / "worklist.csv"
        wl.write_text(
            "review_id,cik,report_date\nRVQ_BLK_scope_dir,0001287750,2025-12-31",
            encoding="utf-8",
        )
        result = validate_dir(vd, wl, ledger_df=_ledger_df_two_ciks())
        assert not result["ok"]
        pf = result["per_file"][0]
        assert not pf["ok"]
        assert any("packet scope" in e or "outside packet" in e for e in pf["errors"])


# ---------------------------------------------------------------------------
# Canary finding 2026-08-25: report_date type normalization in packet scope
# ---------------------------------------------------------------------------


class TestPacketScopeDateNormalization:
    """DuckDB type-infers the ledger's report_date column as TIMESTAMP, so the
    live gate saw '2023-03-31 00:00:00' vs the worklist's '2023-03-31' and
    refused every citation. Packet-scope binding must compare normalized dates."""

    def _df_with_date(self, value):
        df = _ledger_df()
        df["report_date"] = [value]
        return df

    def test_timestamp_string_ledger_date_matches_packet_date(self):
        packet = {"cik": "0001287750", "report_date": "2025-12-31"}
        out = rederive_citations(
            _leaf(), ledger_df=self._df_with_date("2025-12-31 00:00:00"), packet=packet
        )
        assert out["ok"], out["errors"]

    def test_pandas_timestamp_ledger_date_matches_packet_date(self):
        packet = {"cik": "0001287750", "report_date": "2025-12-31"}
        out = rederive_citations(
            _leaf(), ledger_df=self._df_with_date(pd.Timestamp("2025-12-31")), packet=packet
        )
        assert out["ok"], out["errors"]

    def test_iso_t_separator_ledger_date_matches_packet_date(self):
        packet = {"cik": "0001287750", "report_date": "2025-12-31"}
        out = rederive_citations(
            _leaf(), ledger_df=self._df_with_date("2025-12-31T00:00:00"), packet=packet
        )
        assert out["ok"], out["errors"]

    def test_genuinely_different_date_still_refused(self):
        packet = {"cik": "0001287750", "report_date": "2025-12-31"}
        out = rederive_citations(
            _leaf(), ledger_df=self._df_with_date("2025-09-30 00:00:00"), packet=packet
        )
        assert not out["ok"]
        assert any("packet scope" in e or "outside packet" in e for e in out["errors"])

    def test_validate_dir_with_timestamp_ledger_dates(self, tmp_path):
        """End-to-end reproduction of the canary refusal: worklist date is plain,
        ledger date is timestamp-formatted -- must pass after normalization."""
        vd = tmp_path / "verdicts"
        vd.mkdir()
        leaf = {**_leaf(), "review_id": "RVQ_BLK_ts"}
        (vd / "RVQ_BLK_ts.json").write_text(json.dumps(leaf), encoding="utf-8")
        wl = tmp_path / "worklist.csv"
        wl.write_text(
            "review_id,cik,report_date\nRVQ_BLK_ts,0001287750,2025-12-31",
            encoding="utf-8",
        )
        result = validate_dir(
            vd, wl, ledger_df=self._df_with_date("2025-12-31 00:00:00")
        )
        assert result["ok"], result


# ---------------------------------------------------------------------------
# Finding 2: validate_dir missing worklist
# ---------------------------------------------------------------------------


class TestValidateDirMissingWorklist:
    def test_missing_worklist_refuses(self, tmp_path):
        """validate_dir with a non-existent worklist returns ok=False immediately."""
        vd = tmp_path / "verdicts"
        vd.mkdir()
        wl = tmp_path / "no_such_worklist.csv"
        result = validate_dir(vd, wl)
        assert not result["ok"]
        assert result["errors"]
        assert any("worklist not found" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Finding 3: drift_fingerprint.affected_row_ids must cover cited citations
# ---------------------------------------------------------------------------


class TestDriftFingerprintCoverage:
    def test_fingerprint_covering_cited_row_passes(self):
        """parser_drift verdict with cited row_id in affected_row_ids passes."""
        leaf = _leaf(
            verdict="parser_drift",
            drift_fingerprint={
                "field": "interest_rate",
                "transform_code": "rate_x100",
                "affected_row_ids": ["ROW-aaaa"],  # covers the cited row
            },
        )
        out = rederive_citations(leaf, ledger_df=_ledger_df())
        assert out["ok"], out["errors"]

    def test_fingerprint_missing_cited_row_refused(self):
        """parser_drift verdict where cited row_id is NOT in affected_row_ids is refused."""
        leaf = _leaf(
            verdict="parser_drift",
            drift_fingerprint={
                "field": "interest_rate",
                "transform_code": "rate_x100",
                "affected_row_ids": ["ROW-xxxx"],  # does NOT cover ROW-aaaa (the cited row)
            },
        )
        out = rederive_citations(leaf, ledger_df=_ledger_df())
        assert not out["ok"]
        assert any("affected_row_ids" in e for e in out["errors"])

    def test_fingerprint_check_only_runs_for_parser_drift(self):
        """For extraction_wrong, the fingerprint coverage check is not applied."""
        leaf = _leaf(
            verdict="extraction_wrong",
            # No drift_fingerprint -- that is fine for extraction_wrong
        )
        out = rederive_citations(leaf, ledger_df=_ledger_df())
        assert out["ok"], out["errors"]


# ---------------------------------------------------------------------------
# Finding 6: all-malformed citations refuse without full scan
# ---------------------------------------------------------------------------


class TestAllMalformedCitations:
    def test_all_malformed_citations_refused_no_scan(self):
        """When all citations are malformed (missing row_id+field), refuse without scanning."""
        leaf = {
            "review_id": "RVQ_BLK_malformed",
            "verdict": "extraction_wrong",
            "confidence": 0.8,
            "mechanism": "test",
            "culprit_citations": [
                {"declared_raw": 1.0},  # no row_id or field
                {"row_id": "", "field": ""},  # empty row_id and field
            ],
        }
        out = rederive_citations(leaf, ledger_df=_ledger_df())
        assert not out["ok"]
        assert any("malformed" in e for e in out["errors"])
