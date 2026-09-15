"""Homepage largest-positions table and metadata derive from the public snapshot.

Both surfaces must read the ``public_holdings`` temp table that
``public_snapshot`` materialises (cohort filter, latest public quarter, no sign
filter) rather than position_returns.csv or their own read_csv scans.
"""
import json

import duckdb
import pytest

from pipeline.public_partitions import public_snapshot
from tests.test_holdings_finalizer import holdings


def population(tmp_path):
    path = tmp_path / "private_markets_holdings.csv"
    holdings([
        {"row_id": "big", "issuer_name": "Big Loan Co", "entity_id": "E1", "fair_value": "500",
         "cost": "400", "basis_spread": "5.5", "interest_rate": "9.8", "lien_position": "First Lien"},
        {"row_id": "mid", "issuer_name": "Fixed Bond Co", "entity_id": "", "fair_value": "300",
         "cost": "", "basis_spread": "", "interest_rate": "8"},
        {"row_id": "tranche2", "issuer_name": "Big Loan Co", "entity_id": "E1", "fair_value": "120",
         "cost": "200", "index_classification": "COMMON_EQUITY", "cik": "123"},
        {"row_id": "neg", "issuer_name": "Neg Co", "entity_id": "", "fair_value": "-15", "cost": "10"},
        {"row_id": "nullfv", "issuer_name": "Missing Co", "entity_id": "", "fair_value": "", "cost": "50"},
        {"row_id": "outside", "issuer_name": "Not Cohort", "fair_value": "999999", "cik": "0000000999"},
        {"row_id": "older", "issuer_name": "Prior Quarter", "fair_value": "999999", "report_date": "2025-12-31"},
        {"row_id": "future", "issuer_name": "Next Quarter", "fair_value": "999999", "report_date": "2026-06-30"},
    ]).to_csv(path, index=False)
    return path


def snapshot(con, path):
    return public_snapshot(con, path, cutoff="2026-03-31", cohort={"0000000123"},
                           hierarchy={"Software": {"sector": "Information Technology"}})


def _wire(monkeypatch, tmp_path, path):
    from pipeline.export import helpers, index_exports
    monkeypatch.setattr(helpers, "FRONTEND_DATA_DIR", tmp_path)
    monkeypatch.setattr(index_exports, "UNIFIED_HOLDINGS_CSV", path)
    monkeypatch.setattr(index_exports, "POSITION_RETURNS_CSV", tmp_path / "absent_returns.csv")
    monkeypatch.setattr(index_exports, "COMBINED_UNIVERSE_CSV", tmp_path / "absent_universe.csv")
    return index_exports


def test_top_positions_come_from_the_snapshot_population(tmp_path, monkeypatch):
    path = population(tmp_path)
    index_exports = _wire(monkeypatch, tmp_path, path)
    with duckdb.connect() as con:
        result = snapshot(con, path)
        index_exports._export_top_constituents(con, snapshot=result)
    out = json.loads((tmp_path / "top_constituents.json").read_text(encoding="utf-8"))

    assert out["asOf"] == "2026-03-31"
    assert out["basis"] == result["basis"]
    assert out["scope"] == "all_cohort_holdings"
    assert out["positionCount"] == result["positionCount"] == 5
    assert isinstance(out["positions"], list)  # flat, not keyed by index_classification
    names = [p["issuerName"] for p in out["positions"]]
    # Out-of-cohort, prior-quarter and post-cutoff rows never appear, however large.
    assert not {"Not Cohort", "Prior Quarter", "Next Quarter"} & set(names)
    # Signed FV ordering with NULL FV last; both tranches of one issuer are separate rows.
    assert names == ["Big Loan Co", "Fixed Bond Co", "Big Loan Co", "Neg Co", "Missing Co"]
    assert [p["fairValue"] for p in out["positions"]] == [500, 300, 120, -15, None]


def test_top_positions_fields_derive_from_holdings_columns(tmp_path, monkeypatch):
    path = population(tmp_path)
    index_exports = _wire(monkeypatch, tmp_path, path)
    with duckdb.connect() as con:
        index_exports._export_top_constituents(con, snapshot=snapshot(con, path))
    rows = {(p["issuerName"], p["fairValue"]): p
            for p in json.loads((tmp_path / "top_constituents.json").read_text(encoding="utf-8"))["positions"]}

    big = rows[("Big Loan Co", 500)]
    assert big["rateType"] == "Floating"          # basis_spread > 0 wins over interest_rate
    assert big["unrealizedGlPct"] == 25.0         # (500-400)/400
    assert big["cost"] == 400
    assert big["instrument"] == "First Lien"
    assert big["vehicleName"] == "Test BDC"
    assert set(big) == {"issuerName", "vehicleName", "instrument", "fairValue", "cost",
                        "unrealizedGlPct", "rateType"}

    fixed = rows[("Fixed Bond Co", 300)]
    assert fixed["rateType"] == "Fixed"           # interest_rate > 0, no spread
    assert fixed["unrealizedGlPct"] is None       # blank cost -> no G/L
    assert fixed["cost"] is None

    equity = rows[("Big Loan Co", 120)]
    assert equity["rateType"] is None             # neither column populated
    assert equity["unrealizedGlPct"] == -40.0     # (120-200)/200
    assert equity["instrument"] == "Common Equity"


def test_top_positions_limit_and_missing_snapshot(tmp_path, monkeypatch):
    path = population(tmp_path)
    index_exports = _wire(monkeypatch, tmp_path, path)
    with duckdb.connect() as con:
        result = snapshot(con, path)
        index_exports._export_top_constituents(con, snapshot=result, limit=2)
        out = json.loads((tmp_path / "top_constituents.json").read_text(encoding="utf-8"))
        assert [p["issuerName"] for p in out["positions"]] == ["Big Loan Co", "Fixed Bond Co"]
        with pytest.raises(ValueError, match="requires the public snapshot"):
            index_exports._export_top_constituents(con, snapshot=None)


def test_metadata_counts_come_from_the_snapshot_population(tmp_path, monkeypatch):
    path = population(tmp_path)
    index_exports = _wire(monkeypatch, tmp_path, path)
    with duckdb.connect() as con:
        result = snapshot(con, path)
        index_exports._export_metadata(con, [], snapshot=result)
    meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))

    assert meta["asOfQuarter"] == "2026q1"
    assert meta["asOfDate"] == "2026-03-31"
    assert meta["totalAum"] == result["portfolioFv"] == 905     # 500+300+120-15, NULL counted as missing
    assert meta["holdingsCount"] == result["positionCount"] == 5
    assert meta["cikCount"] == 1                                 # '123' and '0000000123' are one CIK
    # entity_id E1 covers both Big Loan Co tranches; blanks fall back to issuer_name.
    assert meta["uniqueIssuers"] == 4
    assert meta["vehicleCount"] == 0                             # universe file absent in this fixture
