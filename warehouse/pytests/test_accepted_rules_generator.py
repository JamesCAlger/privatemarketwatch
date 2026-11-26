"""Text slice R phase 3 fix round 2: the rate-rule generator (scripts/text/accepted_rules_to_wrappers.py) refuses to
write when a legend contradicts an existing code entry, dated or undated, and writes when the new table only extends an
entry. Made-up wrappers in a temporary folder; the real wrappers are not touched."""
import importlib.util
import json
from pathlib import Path

WAREHOUSE = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("accepted_rules_to_wrappers",
                                               WAREHOUSE / "scripts" / "text" / "accepted_rules_to_wrappers.py")
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)

CIK = "0000000009"


def _code(code, rate, first=None, last=None, grade="owner"):
    p = {"code": code, "rate": rate, "source_grade": grade}
    if first:
        p.update(first_filing_date=first, last_filing_date=last)
    return {"target": "rate_text", "action": "rate_code", "parameter": p, "evidence": "made up"}


def _wrapper(tmp_path, rules):
    path = tmp_path / f"{CIK}.json"
    path.write_text(json.dumps({"cik": CIK, "reading_rules": rules}, indent=2) + "\n", encoding="utf-8")
    return path


def test_dated_contradiction_refuses_and_writes_nothing(tmp_path):
    path = _wrapper(tmp_path, [_code("C", "CDOR", "2023-03-31", "2024-03-31")])
    before = path.read_bytes()
    code = gen.write_wrappers({CIK: [_code("C", "CORRA", "2023-06-30", "2025-06-30")]}, str(tmp_path), [CIK])
    assert code == 2
    assert path.read_bytes() == before


def test_undated_contradiction_refuses_and_writes_nothing(tmp_path):
    path = _wrapper(tmp_path, [_code("L", "LIBOR")])
    before = path.read_bytes()
    code = gen.write_wrappers({CIK: [_code("L", "SOFR", "2025-03-31", "2026-06-30")]}, str(tmp_path), [CIK])
    assert code == 2
    assert path.read_bytes() == before


def test_extension_with_the_same_rate_is_written(tmp_path):
    path = _wrapper(tmp_path, [_code("C", "CDOR", "2023-03-31", "2024-03-31")])
    code = gen.write_wrappers({CIK: [_code("C", "CDOR", "2023-03-31", "2024-06-30")]}, str(tmp_path), [CIK])
    assert code == 0
    rules = json.loads(path.read_text(encoding="utf-8"))["reading_rules"]
    assert [r["parameter"]["last_filing_date"] for r in rules] == ["2024-06-30"]


def test_accept_flag_writes_over_a_contradiction(tmp_path):
    path = _wrapper(tmp_path, [_code("C", "CDOR", "2023-03-31", "2024-03-31")])
    code = gen.write_wrappers({CIK: [_code("C", "CORRA", "2023-06-30", "2025-06-30")]}, str(tmp_path), [CIK],
                              accept=True)
    assert code == 0
    assert json.loads(path.read_text(encoding="utf-8"))["reading_rules"][0]["parameter"]["rate"] == "CORRA"
