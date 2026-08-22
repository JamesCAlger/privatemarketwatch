"""Tests for scripts/restamp_row_selectors.py (legacy -> anchor row_id migration)."""

import hashlib
import json

import pandas as pd

from scripts.restamp_row_selectors import build_id_map, restamp_leaves


def _legacy_id(natural_key: str) -> str:
    return "ROW-" + hashlib.md5(natural_key.encode()).hexdigest()[:16]


def _frame() -> pd.DataFrame:
    # minimal unified slice: natural-key inputs + published NEW row_id
    return pd.DataFrame({
        "cik": ["0001287750", "0001287750"],
        "source": ["bdc", "bdc"],
        "report_date": ["2025-12-31", "2025-12-31"],
        "accession_number": ["0001287750-26-000010"] * 2,
        "src_context_id": ["ctx_1", "ctx_2"],
        "bdc_investment_identifier": ["Acme | TL", "Beta | TL"],
        "nport_holding_id": ["", ""],
        "principal_amount": ["1000000", "2000000"],
        "shares_held": ["", ""],
        "bdc_dimensions_raw": ["", ""],
        "row_id": [
            "ROW-" + hashlib.md5(b"bdc|0001287750-26-000010|ctx_1").hexdigest()[:16],
            "ROW-" + hashlib.md5(b"bdc|0001287750-26-000010|ctx_2").hexdigest()[:16],
        ],
    })


def test_build_id_map_maps_legacy_to_new():
    frame = _frame()
    id_map, ambiguous = build_id_map(frame)
    assert not ambiguous
    assert len(id_map) == 2
    assert set(id_map.values()) == set(frame["row_id"])
    for legacy in id_map:
        assert legacy.startswith("ROW-") and legacy not in set(frame["row_id"])


def test_build_id_map_flags_ambiguous_legacy_ids(monkeypatch):
    # compute_natural_keys lot-ordinal disambiguation makes real within-frame
    # legacy-id collisions impossible; the ambiguity path is a defensive guard
    # against that invariant breaking. Simulate the break directly.
    import pipeline.position_id_registry as pir

    frame = _frame()
    monkeypatch.setattr(
        pir, "compute_natural_keys",
        lambda df: pd.Series(["same-key"] * len(df), index=df.index))
    id_map, ambiguous = build_id_map(frame)
    assert ambiguous == [_legacy_id("same-key")]
    assert not id_map  # the shared legacy id must be refused, not guessed


def _write_leaf(dirpath, row_id_value):
    leaf = {
        "cik": "0001287750",
        "fix_class": "all_pik_normalization",
        "template": {"row_selector": {"row_id": row_id_value},
                     "cash_rate": 0.0, "pik_rate": 14.0},
    }
    p = dirpath / "0001287750"
    p.mkdir(parents=True, exist_ok=True)
    f = p / "all_pik_normalization.json"
    f.write_text(json.dumps(leaf, indent=2), encoding="utf-8")
    return f


def test_restamp_rewrites_matching_leaf(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    legacy = next(iter(id_map))
    leaf_file = _write_leaf(tmp_path, legacy)
    changed, unresolved = restamp_leaves(tmp_path, id_map,
                                         current_ids=set(frame["row_id"]),
                                         apply=True)
    assert changed == 1 and not unresolved
    data = json.loads(leaf_file.read_text(encoding="utf-8-sig"))
    assert data["template"]["row_selector"]["row_id"] == id_map[legacy]


def test_restamp_dry_run_writes_nothing(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    legacy = next(iter(id_map))
    leaf_file = _write_leaf(tmp_path, legacy)
    before = leaf_file.read_text(encoding="utf-8")
    changed, unresolved = restamp_leaves(tmp_path, id_map,
                                         current_ids=set(frame["row_id"]),
                                         apply=False)
    assert changed == 1
    assert leaf_file.read_text(encoding="utf-8") == before


def test_restamp_skips_current_ids_and_pulled_dirs(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    current = frame["row_id"].iloc[0]
    _write_leaf(tmp_path, current)  # already new-style: idempotent skip
    pulled = tmp_path / "0009999999" / "_pulled_x_20260101"
    pulled.mkdir(parents=True)
    (pulled / "leaf.json").write_text(
        json.dumps({"template": {"row_selector": {"row_id": "ROW-" + "0" * 16}}}),
        encoding="utf-8")
    changed, unresolved = restamp_leaves(tmp_path, id_map,
                                         current_ids=set(frame["row_id"]),
                                         apply=True)
    assert changed == 0 and not unresolved


def test_restamp_reports_unknown_id(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    _write_leaf(tmp_path, "ROW-" + "f" * 16)  # matches nothing
    changed, unresolved = restamp_leaves(tmp_path, id_map,
                                         current_ids=set(frame["row_id"]),
                                         apply=True)
    assert changed == 0
    assert len(unresolved) == 1


def test_restamp_preserves_bom(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    legacy = next(iter(id_map))
    leaf_file = _write_leaf(tmp_path, legacy)
    raw = leaf_file.read_bytes()
    leaf_file.write_bytes(b"\xef\xbb\xbf" + raw)  # add BOM
    restamp_leaves(tmp_path, id_map, current_ids=set(frame["row_id"]),
                   apply=True)
    assert leaf_file.read_bytes().startswith(b"\xef\xbb\xbf")
