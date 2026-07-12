"""Quarter acceptance contract: is this quarter's cohort data good enough to ship?

Computes a small set of FV-weighted acceptance metrics for ONE target quarter
over the wrapper cohort, evaluates them against thresholds that live in DATA
(``data/reference/quarter_acceptance_thresholds.json``), and writes the verdict
as an artifact:

  - ``data/output/quarter_acceptance.json``       (metrics, checks, verdict)
  - ``data/output/quarter_acceptance_funds.csv``  (per-fund quality tier)

Design intent (2026-07-12):
  - Thresholds are data, not code: the contract can tighten without a deploy,
    and the file carries ``calibration: provisional`` until enough remediation
    waves exist to calibrate it. A provisional gate is a dashboard, not a law.
  - The verdict is computed from artifacts the remediation agents CANNOT edit
    (shadow ledger, review queue, promoted-rule audit), keeping the validation
    layer independent of the correction layer.
  - Per-fund tiers (verified / under_review / unanchored / no_holdings) are the
    seed of the public quality-tier surface: a fund failing the contract ships
    as "under review", it does not block the quarter.

Read-only over its inputs; writes only the two output artifacts. ASCII-only logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline import config

logger = logging.getLogger(__name__)

LEDGER_FILE = config.OUTPUT_DIR / "shadow" / "validation_results_ledger.csv"
QUEUE_FILE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"
AUDIT_FILE = config.OUTPUT_DIR / "agent_fix_application_audit.csv"

FUNDS_COLUMNS = [
    "cik",
    "entity_name",
    "fund_fv_m",
    "conservation_status",
    "conservation_residual_pct",
    "n_blockers",
    "blocker_fv_m",
    "tier",
]

_OPS = {
    ">=": lambda a, v: a >= v,
    "<=": lambda a, v: a <= v,
    ">": lambda a, v: a > v,
    "<": lambda a, v: a < v,
    "==": lambda a, v: a == v,
}


def load_cohort(manifest_path: Path | None = None) -> dict[str, str]:
    """cik10 -> entity_name for the wrapper cohort."""
    path = manifest_path or config.WRAPPER_COHORT_MANIFEST_FILE
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return {
        str(e["cik"]).zfill(10): str(e.get("entity_name") or "")
        for e in data.get("entries", [])
    }


def load_thresholds(path: Path | None = None) -> dict[str, Any]:
    p = path or config.QUARTER_ACCEPTANCE_THRESHOLDS_FILE
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fund_fv_by_quarter(holdings_path: Path, cohort: set[str]) -> dict[tuple[str, str], float]:
    """(cik10, report_date) -> fund FV in USD millions, cohort only (DuckDB)."""
    import duckdb

    src = (
        f"read_csv_auto('{holdings_path.as_posix()}', sample_size=-1)"
        if holdings_path.suffix == ".csv"
        else f"read_parquet('{holdings_path.as_posix()}')"
    )
    con = duckdb.connect()
    con.execute("CREATE TABLE cohort(cik VARCHAR)")
    con.executemany("INSERT INTO cohort VALUES (?)", [(c,) for c in sorted(cohort)])
    rows = con.execute(
        f"""SELECT lpad(CAST(cik AS VARCHAR), 10, '0') AS cik,
                   CAST(report_date AS VARCHAR) AS report_date,
                   sum(TRY_CAST(fair_value AS DOUBLE)) / 1e6 AS fv_m
            FROM {src}
            WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
              AND lpad(CAST(cik AS VARCHAR), 10, '0') IN (SELECT cik FROM cohort)
            GROUP BY 1, 2"""
    ).fetchall()
    return {(c, d): float(v) for c, d, v in rows if v is not None}


def _resolve_metric(metrics: dict[str, Any], dotted: str):
    node: Any = metrics
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def compute_acceptance(
    *,
    target_quarter: str | None = None,
    ledger_path: Path = LEDGER_FILE,
    queue_path: Path = QUEUE_FILE,
    audit_path: Path = AUDIT_FILE,
    holdings_path: Path | None = None,
    manifest_path: Path | None = None,
    thresholds_path: Path | None = None,
) -> dict[str, Any]:
    """Compute the acceptance metrics + threshold checks for one quarter.

    Pure over its input files; does not write anything (see write_acceptance).
    """
    cohort = load_cohort(manifest_path)
    thresholds = load_thresholds(thresholds_path)

    if holdings_path is None:
        from pipeline.review_queue import default_holdings_path

        holdings_path = default_holdings_path()
    if holdings_path is None or not holdings_path.exists():
        raise FileNotFoundError(f"unified holdings not found: {holdings_path}")

    fund_fv = _fund_fv_by_quarter(holdings_path, set(cohort))
    if target_quarter is None:
        if not fund_fv:
            raise ValueError("no cohort holdings found; cannot infer target quarter")
        target_quarter = max(d for _, d in fund_fv)

    fv_in_quarter = {c: v for (c, d), v in fund_fv.items() if d == target_quarter}
    cohort_fv_m = sum(fv_in_quarter.values())

    # --- conservation (shadow ledger; engine artifacts the agents cannot edit) ---
    cons_status: dict[str, tuple[str, float | None]] = {}
    if ledger_path.exists():
        for row in _read_rows(ledger_path):
            if (
                row.get("engine") == "conservation"
                and row.get("rule_name") == "fv_conservation"
                and row.get("period") == target_quarter
            ):
                cik = str(row.get("cik") or "").zfill(10)
                if cik in cohort:
                    metric = row.get("metric")
                    cons_status[cik] = (
                        str(row.get("status") or ""),
                        _f(metric) if metric not in (None, "") else None,
                    )
    else:
        logger.warning("shadow ledger missing, conservation metrics empty: %s", ledger_path)

    n_pass = sum(1 for s, _ in cons_status.values() if s == "pass")
    n_fail = sum(1 for s, _ in cons_status.values() if s == "fail")
    n_skip = sum(1 for s, _ in cons_status.values() if s == "skip")
    flagged_fv_m = sum(
        fv_in_quarter.get(c, 0.0) for c, (s, _) in cons_status.items() if s == "fail"
    )

    # --- source-reconciliation blockers (review queue, blocker lane) ---
    blockers: dict[str, dict[str, float]] = {}
    if queue_path.exists():
        for row in _read_rows(queue_path):
            if (
                row.get("lane") == "blocker"
                and row.get("engine") == "source_recon"
                and row.get("report_date") == target_quarter
            ):
                cik = str(row.get("cik") or "").zfill(10)
                if cik in cohort:
                    b = blockers.setdefault(cik, {"n": 0, "fv_m": 0.0})
                    b["n"] += 1
                    b["fv_m"] += _f(row.get("fv_at_risk_m"))
    else:
        logger.warning("review queue missing, blocker metrics empty: %s", queue_path)

    blocking_fv_m = sum(b["fv_m"] for b in blockers.values())

    # --- promoted-rule application health (rebuild audit; global, not per-quarter) ---
    n_rules = n_noop = n_drift = 0
    if audit_path.exists():
        for row in _read_rows(audit_path):
            n_rules += 1
            if str(row.get("status") or "").lower() != "ok":
                n_noop += 1
            if str(row.get("drift") or "").strip():
                n_drift += 1
    else:
        logger.warning("promoted-rule audit missing, drift metrics empty: %s", audit_path)

    # --- per-fund tiers ---
    funds: list[dict[str, Any]] = []
    tier_counts = {"verified": 0, "under_review": 0, "unanchored": 0, "no_holdings": 0}
    for cik in sorted(cohort):
        fv_m = fv_in_quarter.get(cik)
        status, residual = cons_status.get(cik, ("", None))
        n_blk = int(blockers.get(cik, {}).get("n", 0))
        blk_fv = float(blockers.get(cik, {}).get("fv_m", 0.0))
        if fv_m is None:
            tier = "no_holdings"
        elif status == "fail" or n_blk > 0:
            tier = "under_review"
        elif status == "pass":
            tier = "verified"
        else:
            tier = "unanchored"
        tier_counts[tier] += 1
        funds.append(
            {
                "cik": cik,
                "entity_name": cohort[cik],
                "fund_fv_m": "" if fv_m is None else f"{fv_m:.6f}",
                "conservation_status": status,
                "conservation_residual_pct": "" if residual is None else f"{residual:.3f}",
                "n_blockers": n_blk,
                "blocker_fv_m": f"{blk_fv:.6f}",
                "tier": tier,
            }
        )

    def _share(x: float) -> float:
        return round(100.0 * x / cohort_fv_m, 3) if cohort_fv_m else 0.0

    metrics: dict[str, Any] = {
        "cohort": {
            "funds": len(cohort),
            "funds_with_holdings": len(fv_in_quarter),
            "cohort_fv_m": round(cohort_fv_m, 3),
            "tiers": tier_counts,
            "verified_fv_share_pct": _share(
                sum(
                    fv_in_quarter.get(f["cik"], 0.0)
                    for f in funds
                    if f["tier"] == "verified"
                )
            ),
        },
        "conservation": {
            "n_reconciles": n_pass,
            "n_flagged": n_fail,
            "n_no_anchor": n_skip,
            # anchored_rate is the ASSESSABILITY signal: a fresh quarter whose
            # companyfacts anchors have not landed yet is unmeasurable, not bad.
            "anchored_rate_pct": round(
                100.0 * (n_pass + n_fail) / (n_pass + n_fail + n_skip), 3
            )
            if (n_pass + n_fail + n_skip)
            else 0.0,
            "reconcile_rate_pct": round(100.0 * n_pass / (n_pass + n_fail), 3)
            if (n_pass + n_fail)
            else 0.0,
            "flagged_fv_m": round(flagged_fv_m, 3),
            "flagged_fv_share_pct": _share(flagged_fv_m),
            "band_pct": config.FV_CONSERVATION_BAND_PCT,
        },
        "source_blockers": {
            "n_funds": len(blockers),
            "n_items": sum(int(b["n"]) for b in blockers.values()),
            "blocking_fv_m": round(blocking_fv_m, 3),
            "blocking_fv_share_pct": _share(blocking_fv_m),
        },
        "promoted_rules": {
            "n_rules": n_rules,
            "n_not_ok": n_noop,
            "n_drift": n_drift,
        },
    }

    checks = []
    all_pass = True
    for spec in thresholds.get("checks", []):
        actual = _resolve_metric(metrics, spec["metric"])
        op = spec["op"]
        ok = (
            bool(_OPS[op](float(actual), float(spec["value"])))
            if actual is not None and op in _OPS
            else False
        )
        all_pass = all_pass and ok
        checks.append(
            {
                "id": spec.get("id", spec["metric"]),
                "metric": spec["metric"],
                "op": op,
                "value": spec["value"],
                "actual": actual,
                "pass": ok,
            }
        )

    # Assessability pre-gate: a quarter whose anchors have not landed yet (SEC
    # companyfacts lag) cannot be judged -- NOT_ASSESSABLE, not FAIL. Checks are
    # still computed and reported so the panel stays visible.
    verdict = "PASS" if (all_pass and checks) else "FAIL"
    assess = thresholds.get("assessability")
    if assess:
        a_actual = _resolve_metric(metrics, assess["metric"])
        if a_actual is None or float(a_actual) < float(assess["min"]):
            verdict = "NOT_ASSESSABLE"

    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_quarter": target_quarter,
        "cohort_id": json.loads(
            (manifest_path or config.WRAPPER_COHORT_MANIFEST_FILE).read_text(
                encoding="utf-8-sig"
            )
        ).get("cohort_id"),
        "calibration": thresholds.get("calibration", "provisional"),
        "thresholds_version": thresholds.get("version"),
        "verdict": verdict,
        "checks": checks,
        "metrics": metrics,
        "inputs": {
            "ledger": str(ledger_path),
            "queue": str(queue_path),
            "audit": str(audit_path),
            "holdings": str(holdings_path),
        },
        "_funds": funds,  # stripped before the JSON is written (goes to the CSV)
    }


def write_acceptance(
    result: dict[str, Any],
    *,
    json_path: Path | None = None,
    funds_path: Path | None = None,
) -> tuple[Path, Path]:
    json_path = json_path or config.QUARTER_ACCEPTANCE_FILE
    funds_path = funds_path or config.QUARTER_ACCEPTANCE_FUNDS_FILE
    funds = result.pop("_funds", [])
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    with funds_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FUNDS_COLUMNS)
        w.writeheader()
        for row in funds:
            w.writerow(row)
    return json_path, funds_path


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute the quarter acceptance contract verdict."
    )
    parser.add_argument("--quarter", default=None, help="Target quarter report_date "
                        "(YYYY-MM-DD); default = latest cohort quarter in holdings.")
    parser.add_argument("--ledger", type=Path, default=LEDGER_FILE)
    parser.add_argument("--queue", type=Path, default=QUEUE_FILE)
    parser.add_argument("--audit", type=Path, default=AUDIT_FILE)
    parser.add_argument("--holdings", type=Path, default=None)
    parser.add_argument("--thresholds", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help="JSON output path override.")
    parser.add_argument("--funds-out", type=Path, default=None, help="Funds CSV path override.")
    args = parser.parse_args(argv)

    result = compute_acceptance(
        target_quarter=args.quarter,
        ledger_path=args.ledger,
        queue_path=args.queue,
        audit_path=args.audit,
        holdings_path=args.holdings,
        thresholds_path=args.thresholds,
    )
    verdict, quarter = result["verdict"], result["target_quarter"]
    json_path, funds_path = write_acceptance(
        result, json_path=args.out, funds_path=args.funds_out
    )
    logger.info("quarter %s acceptance: %s (calibration=%s)", quarter, verdict,
                result["calibration"])
    for c in result["checks"]:
        logger.info("  [%s] %-28s %s %s %s (actual %s)",
                    "PASS" if c["pass"] else "FAIL", c["id"], c["metric"], c["op"],
                    c["value"], c["actual"])
    logger.info("wrote %s", json_path)
    logger.info("wrote %s", funds_path)
    return {"PASS": 0, "NOT_ASSESSABLE": 2}.get(verdict, 1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(cli())
