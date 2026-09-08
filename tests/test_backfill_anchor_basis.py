import csv
import json

from scripts.backfill_anchor_basis import backfill, classify_leaf


def _leaf(gt, cf, labels=("Total Investments",), method="total_row", basis=None):
    d = {"cik": "1", "target_quarter": "2026-03-31", "grand_total": gt, "method": method,
         "components": [{"label": l, "value": gt, "source": "s"} for l in labels],
         "companyfacts_fv": cf, "evidence": [{"source": "filing", "quote": "x"}],
         "rationale": "r", "confidence": 0.9}
    if basis:
        d["basis"] = basis
    return d


def test_classify_leaf():
    assert classify_leaf(_leaf(1000.0, 1001.0)) == "investments_ex_cash"
    assert classify_leaf(_leaf(1093.5, 692.0, labels=("Total Debt & Equity Investments",
                                                        "Total Cash Equivalents",
                                                        "Total Short-term Investments"),
                               method="sum_of_schedules")) == "published_rows"
    assert classify_leaf(_leaf(1093.5, 692.0, labels=("Total Investments",))) == ""      # wider, no cash label
    assert classify_leaf(_leaf(1093.5, None)) == ""                                      # no companyfacts
    assert classify_leaf(_leaf(500.0, 692.0)) == ""                                      # below the tag


def test_backfill_writes_and_reports(tmp_path):
    ov = tmp_path / "agent_anchor"
    for i, leaf in enumerate([
        _leaf(1000.0, 1001.0),
        _leaf(1093.5, 692.0, labels=("Total Investments", "Total Money Market Funds")),
        _leaf(1093.5, 692.0),
        _leaf(1.0, 1.0, basis="published_rows"),
    ]):
        p = ov / str(i) / "2026-03-31.json"
        p.parent.mkdir(parents=True)
        leaf["cik"] = str(i)
        p.write_text(json.dumps(leaf), encoding="utf-8")
    (ov / "9").mkdir(); (ov / "9" / "x.json").write_text("{bad", encoding="utf-8")
    out_csv = tmp_path / "unresolved.csv"
    counts = backfill(ov, out_csv, write=True)
    assert counts == {"published_rows": 1, "investments_ex_cash": 1, "unresolved": 1,
                      "already_set": 1, "invalid": 1}
    assert json.loads((ov / "0" / "2026-03-31.json").read_text(encoding="utf-8"))["basis"] == "investments_ex_cash"
    assert json.loads((ov / "1" / "2026-03-31.json").read_text(encoding="utf-8"))["basis"] == "published_rows"
    assert "basis" not in json.loads((ov / "2" / "2026-03-31.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    assert [r["cik"] for r in rows] == ["0000000002"]
    # dry run changes nothing
    (ov / "0" / "2026-03-31.json").write_text(json.dumps(_leaf(1000.0, 1001.0)), encoding="utf-8")
    backfill(ov, out_csv, write=False)
    assert "basis" not in json.loads((ov / "0" / "2026-03-31.json").read_text(encoding="utf-8"))
