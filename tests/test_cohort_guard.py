"""Tests for pipeline.cohort_guard (dispatch-chokepoint cohort scoping)."""

import json

import pytest

from pipeline.cohort_guard import check_worklist, load_cohort_ciks, main


@pytest.fixture
def manifest(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({
        "cohort_id": "test_cohort",
        "held_back_ciks": ["0001377936"],
        "entries": [
            {"rank": 1, "cik": "0001918712", "entity_name": "Ares Strategic"},
            {"rank": 2, "cik": "0001812554", "entity_name": "Blue Owl CIC"},
        ],
    }), encoding="utf-8")
    return p


def test_load_cohort_pads_and_excludes_held_back(manifest):
    cohort = load_cohort_ciks(manifest)
    assert cohort == {"0001918712", "0001812554"}
    assert "0001377936" not in cohort   # held back = failed admission gate


def test_in_cohort_worklist_passes(manifest):
    res = check_worklist(["0001918712", "0001812554"], manifest_path=manifest)
    assert res["ok"] and res["out_of_cohort"] == []


def test_unpadded_cik_forms_match(manifest):
    # dispatch worklists carry mixed formats; "1918712" must not false-positive
    res = check_worklist(["1918712", 1812554], manifest_path=manifest)
    assert res["ok"]


def test_out_of_cohort_refused_and_named(manifest):
    res = check_worklist(["0001918712", "0009999999"], manifest_path=manifest)
    assert not res["ok"]
    assert res["out_of_cohort"] == ["0009999999"]


def test_held_back_cik_is_out_of_cohort(manifest):
    res = check_worklist(["0001377936"], manifest_path=manifest)
    assert not res["ok"]


def test_empty_worklist_is_ok(manifest):
    assert check_worklist([], manifest_path=manifest)["ok"]


def _worklist(tmp_path, rows, column="cik", name="worklist.csv"):
    p = tmp_path / name
    p.write_text(f"{column},target_quarter\n" +
                 "\n".join(f"{c},2026-03-31" for c in rows), encoding="utf-8")
    return p


def test_cli_exit_codes(tmp_path, manifest, capsys):
    ok = _worklist(tmp_path, ["0001918712"], name="ok.csv")
    bad = _worklist(tmp_path, ["0009999999"], name="bad.csv")
    assert main(["--worklist", str(ok), "--manifest", str(manifest)]) == 0
    assert main(["--worklist", str(bad), "--manifest", str(manifest)]) == 1
    assert "0009999999" in capsys.readouterr().out


def test_cli_all_vehicles_bypass_still_reports(tmp_path, manifest, capsys):
    bad = _worklist(tmp_path, ["0009999999"])
    assert main(["--worklist", str(bad), "--manifest", str(manifest),
                 "--all-vehicles"]) == 0
    out = capsys.readouterr().out
    assert "BYPASS" in out and "0009999999" in out


def test_cli_missing_column_is_error_not_pass(tmp_path, manifest):
    wl = _worklist(tmp_path, ["0001918712"], column="not_cik")
    assert main(["--worklist", str(wl), "--manifest", str(manifest)]) == 2
