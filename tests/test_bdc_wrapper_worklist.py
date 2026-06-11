"""Tests for the BDC wrapper claim worklist."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone

from scripts.bdc_wrapper_worklist import build_queue, claim_next, get_stats, load_claims, update_claim


def _write_reference(path, entries):
    path.write_text(
        json.dumps({
            "description": "test reference",
            "entries": entries,
        }),
        encoding="utf-8",
    )


def _write_residuals(path, rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["cik", "mechanism", "issue_count", "affected_source_fair_value"],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_queue_excludes_existing_wrappers_and_no_holdings(tmp_path):
    reference = tmp_path / "reference.json"
    wrapper_dir = tmp_path / "wrappers"
    wrapper_dir.mkdir()
    (wrapper_dir / "0000000004.json").write_text("{}", encoding="utf-8")
    residuals = tmp_path / "residuals.csv"
    _write_reference(
        reference,
        [
            {"cik": "1", "entity_name": "High Priority", "wrapper_status": "none", "has_holdings_data": True, "holdings_rows": 10},
            {"cik": "2", "entity_name": "Already Exists", "wrapper_status": "exists", "has_holdings_data": True, "holdings_rows": 999},
            {"cik": "3", "entity_name": "No Holdings", "wrapper_status": "none", "has_holdings_data": False, "holdings_rows": 999},
            {"cik": "4", "entity_name": "Has File", "wrapper_status": "none", "has_holdings_data": True, "holdings_rows": 999},
            {"cik": "5", "entity_name": "Lower Priority", "wrapper_status": "none", "has_holdings_data": True, "holdings_rows": 200},
        ],
    )
    _write_residuals(
        residuals,
        [
            {"cik": "0000000001", "mechanism": "blocking_source_pct_leaf_parser_mismatch", "issue_count": "5", "affected_source_fair_value": "100"},
            {"cik": "0000000005", "mechanism": "documented_no_fair_value", "issue_count": "99", "affected_source_fair_value": "999"},
        ],
    )

    queue = build_queue(reference_file=reference, wrapper_dir=wrapper_dir, source_residual_file=residuals)

    assert [entry.cik for entry in queue] == ["0000000001", "0000000005"]
    assert queue[0].blocking_issue_count == 5


def test_claim_next_claims_distinct_ciks_and_done_removes_from_remaining(tmp_path):
    reference = tmp_path / "reference.json"
    wrapper_dir = tmp_path / "wrappers"
    wrapper_dir.mkdir()
    claims_file = tmp_path / "claims.json"
    residuals = tmp_path / "residuals.csv"
    _write_reference(
        reference,
        [
            {"cik": "1", "entity_name": "First", "wrapper_status": "none", "has_holdings_data": True, "holdings_rows": 20},
            {"cik": "2", "entity_name": "Second", "wrapper_status": "none", "has_holdings_data": True, "holdings_rows": 10},
        ],
    )
    _write_residuals(residuals, [])

    first = claim_next(
        claims_file=claims_file,
        reference_file=reference,
        wrapper_dir=wrapper_dir,
        source_residual_file=residuals,
        agent="agent-a",
    )
    second = claim_next(
        claims_file=claims_file,
        reference_file=reference,
        wrapper_dir=wrapper_dir,
        source_residual_file=residuals,
        agent="agent-b",
    )

    assert first is not None
    assert second is not None
    assert first.cik == "0000000001"
    assert second.cik == "0000000002"

    update_claim("1", "done", claims_file=claims_file, agent="agent-a", note="validated")
    stats = get_stats(
        claims_file=claims_file,
        reference_file=reference,
        wrapper_dir=wrapper_dir,
        source_residual_file=residuals,
    )

    assert stats["done"] == 1
    assert stats["claimed"] == 1
    assert stats["unclaimed"] == 0
    claims = load_claims(claims_file)
    assert claims["claims"]["0000000001"]["note"] == "validated"


def test_stale_claim_can_be_reclaimed(tmp_path):
    reference = tmp_path / "reference.json"
    wrapper_dir = tmp_path / "wrappers"
    wrapper_dir.mkdir()
    claims_file = tmp_path / "claims.json"
    residuals = tmp_path / "residuals.csv"
    _write_reference(
        reference,
        [
            {"cik": "1", "entity_name": "First", "wrapper_status": "none", "has_holdings_data": True, "holdings_rows": 20},
        ],
    )
    _write_residuals(residuals, [])
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).replace(microsecond=0).isoformat()
    claims_file.write_text(
        json.dumps({
            "schema_version": "bdc-wrapper-claims.v1",
            "claims": {
                "0000000001": {
                    "status": "claimed",
                    "claimed_at": old,
                    "claimed_by": "old-agent",
                },
            },
        }),
        encoding="utf-8",
    )

    entry = claim_next(
        claims_file=claims_file,
        reference_file=reference,
        wrapper_dir=wrapper_dir,
        source_residual_file=residuals,
        agent="new-agent",
        stale_hours=24,
    )

    assert entry is not None
    claims = load_claims(claims_file)
    claim = claims["claims"]["0000000001"]
    assert claim["claimed_by"] == "new-agent"
    assert claim["reclaimed_previous_claim"]["claimed_by"] == "old-agent"
