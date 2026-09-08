"""Tests for the quarter acceptance contract (pipeline/quarter_acceptance.py)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from pipeline import quarter_acceptance as qa

LEDGER_HEADER = [
    "engine", "rule_name", "tier", "enforcement", "cik", "period_kind",
    "period", "status", "metric", "metric_name", "n_units", "mechanism",
    "src_confidence", "confidence", "surface",
]
QUEUE_HEADER = [
    "priority_rank", "review_id", "lane", "anchor", "engine", "rule_name",
    "tier", "enforcement", "cik", "report_date", "period", "period_kind",
    "unit_label", "status", "mechanism", "confidence", "src_confidence",
    "surface", "n_units", "metric_name", "metric", "fv_at_risk_m",
    "fund_quarter_fv_m",
]
AUDIT_HEADER = [
    "layer", "cik", "rule_id", "rule_type", "status", "rows_changed",
    "fv_affected", "authoring_rows", "authoring_fv", "drift", "message",
]

Q = "2025-12-31"


def _csv(path: Path, header: list[str], rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})
    return path


def _manifest(path: Path, ciks: list[str]) -> Path:
    path.write_text(json.dumps({
        "cohort_id": "test_cohort",
        "entries": [{"cik": c, "entity_name": f"Fund {c}"} for c in ciks],
    }), encoding="utf-8")
    return path


def _thresholds(path: Path, *, min_anchored: float = 50.0, checks: list | None = None) -> Path:
    if checks is None:
        checks = [
            {"id": "reconcile_rate", "metric": "conservation.reconcile_rate_pct",
             "op": ">=", "value": 50.0},
            {"id": "flagged_fv_share", "metric": "conservation.flagged_fv_share_pct",
             "op": "<=", "value": 30.0},
            {"id": "drift", "metric": "promoted_rules.n_drift", "op": "<=", "value": 0},
        ]
    path.write_text(json.dumps({
        "version": 99,
        "calibration": "provisional",
        "assessability": {"metric": "conservation.anchored_rate_pct", "min": min_anchored},
        "checks": checks,
    }), encoding="utf-8")
    return path


def _holdings(path: Path, rows: list[tuple[str, str, float]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cik", "report_date", "fair_value"])
        for cik, d, fv in rows:
            w.writerow([cik, d, fv])
    return path


def _cons_row(cik: str, status: str, metric: str = "0.1") -> dict:
    return {"engine": "conservation", "rule_name": "fv_conservation", "tier": "tight",
            "cik": cik, "period_kind": "report_date", "period": Q,
            "status": status, "metric": metric}


def _setup(tmp_path: Path, *, ledger_rows: list[dict], queue_rows: list[dict] | None = None,
           audit_rows: list[dict] | None = None,
           holdings_rows: list[tuple[str, str, float]] | None = None,
           ciks: list[str] | None = None, min_anchored: float = 50.0):
    ciks = ciks or ["0000000001", "0000000002", "0000000003"]
    if holdings_rows is None:
        holdings_rows = [(c, Q, 100_000_000.0) for c in ciks]
    return dict(
        ledger_path=_csv(tmp_path / "ledger.csv", LEDGER_HEADER, ledger_rows),
        queue_path=_csv(tmp_path / "queue.csv", QUEUE_HEADER, queue_rows or []),
        audit_path=_csv(tmp_path / "audit.csv", AUDIT_HEADER, audit_rows or []),
        holdings_path=_holdings(tmp_path / "holdings.csv", holdings_rows),
        manifest_path=_manifest(tmp_path / "manifest.json", ciks),
        thresholds_path=_thresholds(tmp_path / "thresholds.json", min_anchored=min_anchored),
    )


def test_pass_verdict_and_tiers(tmp_path):
    kw = _setup(tmp_path, ledger_rows=[
        _cons_row("0000000001", "pass"),
        _cons_row("0000000002", "pass"),
        _cons_row("0000000003", "fail", "9.9"),
    ])
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    tiers = {f["cik"]: f["tier"] for f in res["_funds"]}
    assert tiers == {"0000000001": "verified", "0000000002": "verified",
                     "0000000003": "under_review"}
    m = res["metrics"]["conservation"]
    assert m["n_reconciles"] == 2 and m["n_flagged"] == 1 and m["n_no_anchor"] == 0
    assert m["anchored_rate_pct"] == 100.0
    assert round(m["reconcile_rate_pct"], 1) == 66.7
    # each fund holds 100M of a 300M cohort -> flagged share 33.3 > 30 threshold
    assert res["checks"][1]["pass"] is False
    assert res["verdict"] == "FAIL"


def test_pass_when_all_checks_clear(tmp_path):
    kw = _setup(tmp_path, ledger_rows=[
        _cons_row("0000000001", "pass"),
        _cons_row("0000000002", "pass"),
        _cons_row("0000000003", "pass"),
    ])
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    assert res["verdict"] == "PASS"
    assert all(c["pass"] for c in res["checks"])
    assert res["metrics"]["cohort"]["verified_fv_share_pct"] == 100.0


def test_not_assessable_when_anchors_missing(tmp_path):
    kw = _setup(tmp_path, ledger_rows=[
        _cons_row("0000000001", "skip", ""),
        _cons_row("0000000002", "skip", ""),
        _cons_row("0000000003", "pass"),
    ])
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    # anchored rate 33.3 < 50 -> not assessable, checks still reported
    assert res["verdict"] == "NOT_ASSESSABLE"
    assert res["metrics"]["conservation"]["anchored_rate_pct"] == round(100.0 / 3, 3)
    assert len(res["checks"]) == 3
    tiers = {f["cik"]: f["tier"] for f in res["_funds"]}
    assert tiers["0000000001"] == "unanchored"


def test_blockers_put_fund_under_review_and_fv_weighted(tmp_path):
    kw = _setup(
        tmp_path,
        ledger_rows=[_cons_row("0000000001", "pass"), _cons_row("0000000002", "pass"),
                     _cons_row("0000000003", "pass")],
        queue_rows=[
            {"lane": "blocker", "engine": "source_recon", "cik": "0000000002",
             "report_date": Q, "fv_at_risk_m": "12.5"},
            {"lane": "blocker", "engine": "source_recon", "cik": "0000000002",
             "report_date": Q, "fv_at_risk_m": "7.5"},
            # review lane must NOT count as a blocker
            {"lane": "review", "engine": "row_validation", "cik": "0000000001",
             "report_date": Q, "fv_at_risk_m": ""},
        ],
    )
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    tiers = {f["cik"]: f["tier"] for f in res["_funds"]}
    assert tiers["0000000002"] == "under_review"
    assert tiers["0000000001"] == "verified"
    sb = res["metrics"]["source_blockers"]
    assert sb["n_funds"] == 1 and sb["n_items"] == 2
    assert sb["blocking_fv_m"] == 20.0
    # 20M of 300M cohort
    assert sb["blocking_fv_share_pct"] == round(100.0 * 20.0 / 300.0, 3)


def test_promoted_rule_drift_fails_contract(tmp_path):
    kw = _setup(
        tmp_path,
        ledger_rows=[_cons_row("0000000001", "pass"), _cons_row("0000000002", "pass"),
                     _cons_row("0000000003", "pass")],
        audit_rows=[
            {"layer": "unified_agent_rules", "cik": "0000000001", "rule_id": "r1",
             "status": "ok", "drift": ""},
            {"layer": "unified_agent_rules", "cik": "0000000002", "rule_id": "r2",
             "status": "ok", "drift": "rows_changed 0 vs authoring 46"},
        ],
    )
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    assert res["metrics"]["promoted_rules"]["n_drift"] == 1
    drift_check = next(c for c in res["checks"] if c["id"] == "drift")
    assert drift_check["pass"] is False
    assert res["verdict"] == "FAIL"


def test_fund_without_holdings_tiered_no_holdings(tmp_path):
    kw = _setup(
        tmp_path,
        ledger_rows=[_cons_row("0000000001", "pass"), _cons_row("0000000002", "pass")],
        holdings_rows=[("0000000001", Q, 100_000_000.0), ("0000000002", Q, 50_000_000.0)],
    )
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    tiers = {f["cik"]: f["tier"] for f in res["_funds"]}
    assert tiers["0000000003"] == "no_holdings"
    assert res["metrics"]["cohort"]["funds_with_holdings"] == 2


def test_missing_metric_path_fails_closed(tmp_path):
    kw = _setup(tmp_path, ledger_rows=[
        _cons_row("0000000001", "pass"), _cons_row("0000000002", "pass"),
        _cons_row("0000000003", "pass"),
    ])
    kw["thresholds_path"] = _thresholds(
        tmp_path / "t2.json",
        checks=[{"id": "bogus", "metric": "no.such.metric", "op": ">=", "value": 1}],
    )
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    assert res["checks"][0]["pass"] is False
    assert res["verdict"] == "FAIL"


def test_write_acceptance_artifacts(tmp_path):
    kw = _setup(tmp_path, ledger_rows=[
        _cons_row("0000000001", "pass"), _cons_row("0000000002", "pass"),
        _cons_row("0000000003", "pass"),
    ])
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    jp, fp = qa.write_acceptance(
        res, json_path=tmp_path / "qa.json", funds_path=tmp_path / "qa_funds.csv"
    )
    data = json.loads(jp.read_text(encoding="utf-8"))
    assert "_funds" not in data
    assert data["verdict"] == "PASS"
    assert data["target_quarter"] == Q
    with fp.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert set(rows[0].keys()) == set(qa.FUNDS_COLUMNS)


def test_stale_investigations_counted_for_cohort_only(tmp_path):
    inv = tmp_path / "agent_investigate"
    for cik, in_cohort in (("1", True), ("9", False)):
        d = inv / cik / "rules"
        d.mkdir(parents=True)
        (d / "r.json").write_text("{}", encoding="utf-8")       # rules, never applied -> stale
    kw = _setup(tmp_path, ledger_rows=[_cons_row("0000000001", "pass"),
                                       _cons_row("0000000002", "pass"),
                                       _cons_row("0000000003", "pass")])
    res = qa.compute_acceptance(target_quarter=Q, investigate_dir=inv, **kw)
    assert res["metrics"]["investigations"] == {
        "n_stale": 1, "stale_ciks": ["0000000001"], "measured": True}


def test_missing_investigate_dir_is_not_measured(tmp_path):
    """A missing investigation store is UNMEASURED, not clean.

    Supersedes the Plan 1 fail-open behaviour (missing dir == zero stale): under
    thresholds v3 ``unfinished_investigations`` is a blocking check, so a metric that
    reads 0 whenever ``data/output/agent_investigate/`` is absent is a gate anyone can
    satisfy by renaming a directory -- which is not a gate (spec validation-layer
    principle: the verdict must not be reachable by editing the correction layer).
    """
    kw = _setup(tmp_path, ledger_rows=[_cons_row("0000000001", "pass"),
                                       _cons_row("0000000002", "pass"),
                                       _cons_row("0000000003", "pass")])
    res = qa.compute_acceptance(target_quarter=Q, investigate_dir=tmp_path / "nope", **kw)
    assert res["metrics"]["investigations"] == {
        "n_stale": None, "stale_ciks": [], "measured": False}


def test_unfinished_investigations_fails_closed_when_store_missing(tmp_path):
    """The blocking check FAILS on an absent store rather than passing on a 0."""
    kw = _setup(tmp_path, ledger_rows=[_cons_row("0000000001", "pass"),
                                       _cons_row("0000000002", "pass"),
                                       _cons_row("0000000003", "pass")])
    kw["thresholds_path"] = _thresholds(
        tmp_path / "t_inv.json",
        checks=[{"id": "unfinished_investigations", "metric": "investigations.n_stale",
                 "op": "<=", "value": 0}],
    )
    res = qa.compute_acceptance(target_quarter=Q, investigate_dir=tmp_path / "nope", **kw)
    check = next(c for c in res["checks"] if c["id"] == "unfinished_investigations")
    assert check["pass"] is False
    assert check["actual"] is None
    assert res["verdict"] == "FAIL"


def test_fund_fv_uses_published_basis_on_timestamp_report_date(tmp_path):
    """A TIMESTAMP-shaped report_date must not zero every FV metric.

    Typed parquet renders report_date as '2025-12-31 00:00:00'; the acceptance sum used
    to hand-roll CAST(report_date AS VARCHAR), so nothing equalled the target quarter and
    cohort/flagged/over-inclusion FV all read 0 -- the v3 FV gates passed vacuously.
    Routing through published_basis.published_fv_sum_sql keys on the 10-char date and a
    10-digit cik, so an unpadded cik and a timestamped date both land.
    """
    kw = _setup(
        tmp_path,
        ciks=["1", "2"],
        holdings_rows=[("1", f"{Q} 00:00:00", 100_000_000.0),
                       ("2", f"{Q} 00:00:00", 50_000_000.0)],
        ledger_rows=[_cons_row("0000000001", "pass"), _cons_row("0000000002", "fail", "10.0")],
    )
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    cohort = res["metrics"]["cohort"]
    assert cohort["cohort_fv_m"] == 150.0
    assert cohort["funds_with_holdings"] == 2
    assert res["metrics"]["conservation"]["flagged_fv_m"] == 50.0
    assert res["metrics"]["conservation"]["over_inclusion_fv_m"] > 0.0


def test_over_inclusion_metric_and_anchor_basis(tmp_path):
    """Bain Q1-26 shape: fund FV 2221.6M at +22.4% residual -> 406.5M over-included.
    An undershoot contributes 0. Share is against cohort FV."""
    ciks = ["0000000001", "0000000002", "0000000003"]
    kw = _setup(tmp_path, ciks=ciks,
                holdings_rows=[("0000000001", Q, 2_221_600_000.0),
                               ("0000000002", Q, 1_000_000_000.0),
                               ("0000000003", Q, 778_400_000.0)],
                ledger_rows=[
                    {**_cons_row("0000000001", "fail", "22.4"), "mechanism": "verified_override:published_rows"},
                    {**_cons_row("0000000002", "fail", "-3.0"), "mechanism": "companyfacts_fv:investments_ex_cash"},
                    {**_cons_row("0000000003", "pass", "0.1"), "mechanism": "companyfacts_fv_plus_cash:published_rows"},
                ])
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    m = res["metrics"]["conservation"]
    assert abs(m["over_inclusion_fv_m"] - 406.5) < 0.2
    assert abs(m["over_inclusion_fv_share_pct"] - 100 * 406.5 / 4000.0) < 0.01
    funds = {f["cik"]: f for f in res["_funds"]}
    assert abs(float(funds["0000000001"]["over_inclusion_fv_m"]) - 406.5) < 0.2
    assert float(funds["0000000002"]["over_inclusion_fv_m"]) == 0.0
    assert funds["0000000001"]["anchor_basis"] == "published_rows"
    assert funds["0000000002"]["anchor_basis"] == "investments_ex_cash"
    assert funds["0000000003"]["anchor_basis"] == "published_rows"


def test_over_inclusion_gate_from_thresholds(tmp_path):
    ciks = ["0000000001", "0000000002"]
    checks = [{"id": "over_inclusion_fv_share", "metric": "conservation.over_inclusion_fv_share_pct",
               "op": "<=", "value": 0.5}]
    kw = _setup(tmp_path, ciks=ciks,
                holdings_rows=[("0000000001", Q, 1_010_000_000.0), ("0000000002", Q, 990_000_000.0)],
                ledger_rows=[_cons_row("0000000001", "fail", "1.01"), _cons_row("0000000002", "pass")])
    kw["thresholds_path"] = _thresholds(tmp_path / "t3.json", checks=checks)
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    # over-inclusion = 1010 - 1010/1.0101 = 10.1M of 2000M = 0.505% -> FAIL at 0.5
    assert res["checks"][0]["pass"] is False and res["verdict"] == "FAIL"
    kw["thresholds_path"] = _thresholds(tmp_path / "t4.json", checks=[{**checks[0], "value": 0.51}])
    assert qa.compute_acceptance(target_quarter=Q, **kw)["verdict"] == "PASS"


def test_thresholds_v3_file_has_nine_checks():
    from pipeline import config
    t = json.loads(config.QUARTER_ACCEPTANCE_THRESHOLDS_FILE.read_text(encoding="utf-8-sig"))
    ids = [c["id"] for c in t["checks"]]
    assert t["version"] == 3
    assert ids == ["fund_coverage", "reconcile_rate", "flagged_fv_share", "source_blocking_fv_share",
                   "verified_fv_share", "promoted_rule_drift", "promoted_rule_health",
                   "over_inclusion_fv_share", "unfinished_investigations"]
    by_id = {c["id"]: c for c in t["checks"]}
    assert by_id["over_inclusion_fv_share"] == {
        "id": "over_inclusion_fv_share", "metric": "conservation.over_inclusion_fv_share_pct",
        "op": "<=", "value": 0.5, "note": by_id["over_inclusion_fv_share"]["note"]}
    assert by_id["unfinished_investigations"]["metric"] == "investigations.n_stale"
    assert by_id["unfinished_investigations"]["op"] == "<=" and by_id["unfinished_investigations"]["value"] == 0
