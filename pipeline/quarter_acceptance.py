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
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline import config

logger = logging.getLogger(__name__)

LEDGER_FILE = config.OUTPUT_DIR / "shadow" / "validation_results_ledger.csv"
QUEUE_FILE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"
AUDIT_FILE = config.OUTPUT_DIR / "agent_fix_application_audit.csv"
# Written by the unified build next to the application audit (rule_admission._write);
# by default it is read from the SAME directory as ``audit_path`` so both audits
# always describe one build.
ADMISSION_AUDIT_NAME = "input_admission_audit.csv"
INVESTIGATE_DIR = config.OUTPUT_DIR / "agent_investigate"
FINDINGS_LEDGER_FILE = config.OUTPUT_DIR / "agent_b2" / "findings_ledger.csv"
# Findings-ledger states that need no further work. Every other state, including one
# this module has never seen, is outstanding (owner ruling 2026-10-05).
RESOLVED_FINDING_STATES = frozenset({"adjudicated_false_alarm", "remediated_promoted",
                                     "resolved_upstream", "gone_unadjudicated",
                                     # owner-retired real-error verdict, check silent
                                     # (pipeline.verdict_retirements). real_error_check_silent
                                     # is deliberately absent: it stays outstanding.
                                     "verdict_retired",
                                     # standing dispositions (pipeline.finding_dispositions)
                                     "dispositioned_informational", "dispositioned_as_filed",
                                     "dispositioned_not_applicable"})

FUNDS_COLUMNS = [
    "cik",
    "entity_name",
    "fund_fv_m",
    "conservation_status",
    "conservation_residual_pct",
    "over_inclusion_fv_m",
    "anchor_basis",
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
    """(cik10, report_date) -> fund FV in USD millions, cohort only (DuckDB).

    The sum IS the published-basis numerator (``pipeline.published_basis``): a 10-digit
    cik, a 10-char report_date key, and no category/dimension/subsidiary filter. Routing
    through the single definition keeps every acceptance FV metric on exactly the rows
    the public headline publishes, and makes a TIMESTAMP-typed report_date (typed parquet
    renders '2025-12-31 00:00:00') compare equal to the target quarter instead of
    silently emptying cohort/flagged/over-inclusion FV and passing the gates vacuously.
    The cohort/quarter restriction lives OUTSIDE the numerator, never inside it.
    """
    import duckdb

    from pipeline.published_basis import published_fv_sum_sql

    src = (
        f"read_csv_auto('{holdings_path.as_posix()}', sample_size=-1)"
        if holdings_path.suffix == ".csv"
        else f"read_parquet('{holdings_path.as_posix()}')"
    )
    con = duckdb.connect()
    con.execute("CREATE TABLE cohort(cik VARCHAR)")
    con.executemany("INSERT INTO cohort VALUES (?)", [(c,) for c in sorted(cohort)])
    rows = con.execute(
        f"""SELECT cik, report_date, value_sum / 1e6 AS fv_m
            FROM ({published_fv_sum_sql(src)}) AS published
            WHERE cik IN (SELECT cik FROM cohort)"""
    ).fetchall()
    con.close()
    return {(c, d): float(v) for c, d, v in rows if v is not None}


def _numeric(value) -> float | None:
    """float(value), or None if the metric is missing/unmeasured/non-numeric.

    A check whose actual is not a number is not comparable, so it must fail closed
    rather than raise: an exception here would take the whole verdict down.
    """
    if value is None or isinstance(value, (bool, list, dict, tuple, set)):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


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
    admission_path: Path | None = None,
    holdings_path: Path | None = None,
    manifest_path: Path | None = None,
    thresholds_path: Path | None = None,
    investigate_dir: Path | None = None,
    findings_ledger_path: Path | None = None,
    programme_evidence: Path | None = None,
    programme_thresholds: Path | None = None,
    programme_pair_cache: set | None = None,
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
    # cik -> (status, residual_pct, anchor_basis). The ledger's conservation mechanism is
    # "<anchor_used>:<anchor_basis>", so the basis is the last colon-separated segment.
    cons_status: dict[str, tuple[str, float | None, str]] = {}
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
                        str(row.get("mechanism") or "").split(":")[-1],
                    )
    else:
        logger.warning("shadow ledger missing, conservation metrics empty: %s", ledger_path)

    n_pass = sum(1 for s, _, _ in cons_status.values() if s == "pass")
    n_fail = sum(1 for s, _, _ in cons_status.values() if s == "fail")
    n_skip = sum(1 for s, _, _ in cons_status.values() if s == "skip")
    flagged_fv_m = sum(
        fv_in_quarter.get(c, 0.0) for c, (s, _, _) in cons_status.items() if s == "fail"
    )

    # Over-inclusion (spec 2026-09-07 s.3): FV above the anchor across failed funds. With the
    # published-basis numerator, value_sum == fund FV, so over = fv - fv / (1 + r/100).
    def _over(c: str) -> float:
        s, r, _ = cons_status.get(c, ("", None, ""))
        fv = fv_in_quarter.get(c, 0.0)
        if s == "fail" and r is not None and r > 0 and fv > 0:
            return fv - fv / (1.0 + r / 100.0)
        return 0.0

    over_by_fund = {c: _over(c) for c in cons_status}
    over_inclusion_fv_m = sum(over_by_fund.values())

    # --- source-reconciliation blockers (review queue, blocker lane) ---
    # A blocker the findings ledger has resolved (disposition, false alarm, fix) is not
    # blocking (owner ruling 2026-11-06). One the ledger does not know, or every blocker when
    # the ledger is missing, still counts: the check fails closed.
    findings_path = findings_ledger_path or FINDINGS_LEDGER_FILE
    resolved_ids = ({row.get("review_id") for row in _read_rows(findings_path)
                     if row.get("state") in RESOLVED_FINDING_STATES} - {None, ""}
                    if findings_path.exists() else set())
    blockers: dict[str, dict[str, float]] = {}
    n_blockers_raw = n_blockers_resolved = 0
    if queue_path.exists():
        for row in _read_rows(queue_path):
            if (
                row.get("lane") == "blocker"
                and row.get("engine") == "source_recon"
                and row.get("report_date") == target_quarter
            ):
                cik = str(row.get("cik") or "").zfill(10)
                if cik in cohort:
                    n_blockers_raw += 1
                    if row.get("review_id") in resolved_ids:
                        n_blockers_resolved += 1
                        continue
                    b = blockers.setdefault(cik, {"n": 0, "fv_m": 0.0})
                    b["n"] += 1
                    b["fv_m"] += _f(row.get("fv_at_risk_m"))
    else:
        logger.warning("review queue missing, blocker metrics empty: %s", queue_path)

    blocking_fv_m = sum(b["fv_m"] for b in blockers.values())

    # --- promoted-rule application health (rebuild audit; global, not per-quarter) ---
    # A rule labelled 'pending' (every target quarter absent from the build, owner ruling
    # D-253) is listed, not counted: it has nothing to match yet. A rule whose quarters ARE
    # in the build and changes 0 rows keeps its 'noop' label and still counts.
    from pipeline.agent_promoted import PENDING
    n_rules = n_noop = n_drift = 0
    pending_rules: list[dict[str, str]] = []
    if audit_path.exists():
        for row in _read_rows(audit_path):
            n_rules += 1
            if str(row.get("status") or "").lower() != "ok":
                n_noop += 1
            drift_label = str(row.get("drift") or "").strip()
            if drift_label == PENDING:
                pending_rules.append({"cik": str(row.get("cik") or ""),
                                      "rule_id": str(row.get("rule_id") or ""),
                                      "message": str(row.get("message") or "")})
            elif drift_label:
                n_drift += 1
    else:
        logger.warning("promoted-rule audit missing, drift metrics empty: %s", audit_path)

    # --- promoted inputs that failed to LOAD (admission audit of the same build) ---
    # The application audit above only lists fixes that reached an applier. A promoted
    # file the loader rejected, could not read, or dropped never appears there, so it
    # would be silent. Any such file counts against promoted_rule_health (zero
    # tolerance, same threshold): retire it or repair it. The loader runs more than once
    # per build, so failures are counted per distinct file path, not per audit row.
    from pipeline.rule_admission import LOAD_FAILURE_STATUSES
    admission_path = admission_path or audit_path.parent / ADMISSION_AUDIT_NAME
    admission_measured = admission_path.exists()
    load_rejected: dict[str, str] = {}
    if admission_measured:
        for row in _read_rows(admission_path):
            status = str(row.get("admission_status") or "").strip()
            if status in LOAD_FAILURE_STATUSES:
                load_rejected[str(row.get("path") or "")] = status
        for path, status in sorted(load_rejected.items()):
            logger.warning("promoted input failed to load (%s): %s", status, ascii(path))
    else:
        # Fail closed, like investigations.n_stale: with no admission audit the
        # load-failure count is UNMEASURED (None), so promoted_rule_health cannot
        # pass on a comfortable 0. Deleting or misplacing the audit is not a pass.
        logger.warning("input admission audit missing, load-rejection metric unmeasured: %s",
                       admission_path)
    n_load_rejected = len(load_rejected) if admission_measured else None

    # --- unfinished investigations (staged rules newer than their apply/gate) ---
    # A gate a rename can satisfy is not a gate (spec validation-layer principle): if the
    # investigation store is absent the metric is UNMEASURED (n_stale None), so the blocking
    # unfinished_investigations check fails closed instead of reading a comfortable 0. This
    # deliberately supersedes the earlier fail-open "missing dir == zero stale" behaviour.
    from pipeline.investigation_state import stale_investigations
    inv_dir = investigate_dir or INVESTIGATE_DIR
    inv_measured = inv_dir.exists()
    stale = stale_investigations(inv_dir, target_quarter, ciks=set(cohort)) if inv_measured else []
    if not inv_measured:
        logger.warning("agent_investigate dir missing, stale metric unmeasured: %s", inv_dir)

    # --- outstanding findings (sign-off quarter, every unresolved state) ---
    # Scope comes from the thresholds file; absent, it is the whole cohort. A missing
    # ledger is UNMEASURED (None) so the check fails closed, like n_stale above.
    # findings_path is set with the source blockers above.
    findings_scope = sorted(str(c).zfill(10) for c in
                            (thresholds.get("findings_scope") or {}).get("ciks") or cohort)
    findings_measured = findings_path.exists()
    outstanding_by_state: dict[str, int] = {}
    if findings_measured:
        for row in _read_rows(findings_path):
            if (str(row.get("cik") or "").zfill(10) in findings_scope
                    and str(row.get("report_date") or "")[:10] == target_quarter
                    and row.get("state") not in RESOLVED_FINDING_STATES):
                state = row.get("state") or ""
                outstanding_by_state[state] = outstanding_by_state.get(state, 0) + 1
    else:
        logger.warning("findings ledger missing, outstanding findings unmeasured: %s",
                       findings_path)

    # --- per-fund tiers ---
    funds: list[dict[str, Any]] = []
    tier_counts = {"verified": 0, "under_review": 0, "unanchored": 0, "no_holdings": 0}
    for cik in sorted(cohort):
        fv_m = fv_in_quarter.get(cik)
        status, residual, basis = cons_status.get(cik, ("", None, ""))
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
                "over_inclusion_fv_m": f"{over_by_fund.get(cik, 0.0):.6f}",
                "anchor_basis": basis,
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
            "over_inclusion_fv_m": round(over_inclusion_fv_m, 3),
            "over_inclusion_fv_share_pct": _share(over_inclusion_fv_m),
            "band_pct": config.FV_CONSERVATION_BAND_PCT,
        },
        "source_blockers": {
            "n_funds": len(blockers),
            "n_items": sum(int(b["n"]) for b in blockers.values()),
            "n_items_raw": n_blockers_raw,
            "n_items_resolved": n_blockers_resolved,
            "blocking_fv_m": round(blocking_fv_m, 3),
            "blocking_fv_share_pct": _share(blocking_fv_m),
        },
        "promoted_rules": {
            "n_rules": n_rules,
            # n_not_ok is what promoted_rule_health gates on: fixes that reached an
            # applier and did not apply cleanly, PLUS promoted files that never loaded.
            # None (unmeasured, check fails) when the admission audit is missing.
            "n_not_ok": n_noop + n_load_rejected if admission_measured else None,
            "n_apply_not_ok": n_noop,
            "n_load_rejected": n_load_rejected,
            "load_rejected_paths": sorted(load_rejected),
            "admission_measured": admission_measured,
            "n_drift": n_drift,
            "n_pending": len(pending_rules),
            "pending_rules": pending_rules,
        },
        "investigations": {
            "n_stale": len(stale) if inv_measured else None,
            "stale_ciks": [s["cik"] for s in stale],
            "measured": inv_measured,
        },
        "findings": {
            "n_outstanding": sum(outstanding_by_state.values()) if findings_measured else None,
            "by_state": outstanding_by_state,
            "scope_ciks": findings_scope,
            "measured": findings_measured,
        },
    }

    checks = []
    all_pass = True
    for spec in thresholds.get("checks", []):
        actual = _resolve_metric(metrics, spec["metric"])
        op = spec["op"]
        num = _numeric(actual)
        ok = bool(_OPS[op](num, float(spec["value"]))) if num is not None and op in _OPS else False
        all_pass = all_pass and ok
        checks.append(
            {
                "id": spec.get("id", spec["metric"]),
                "metric": spec["metric"],
                "op": op,
                "value": spec["value"],
                "actual": actual if num is not None else None,
                "pass": ok,
            }
        )

    # Assessability pre-gate: a quarter whose anchors have not landed yet (SEC
    # companyfacts lag) cannot be judged -- NOT_ASSESSABLE, not FAIL. Checks are
    # still computed and reported so the panel stays visible.
    verdict = "PASS" if (all_pass and checks) else "FAIL"
    assess = thresholds.get("assessability")
    if assess:
        a_actual = _numeric(_resolve_metric(metrics, assess["metric"]))
        if a_actual is None or a_actual < float(assess["min"]):
            verdict = "NOT_ASSESSABLE"

    result = {
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
            "admission": str(admission_path),
            "holdings": str(holdings_path),
            "investigate": str(inv_dir),
            "findings_ledger": str(findings_path),
        },
        "_funds": funds,  # stripped before the JSON is written (goes to the CSV)
    }
    if programme_evidence is not None:
        from pipeline.quarter_evidence import Evidence,collect
        evidence=Evidence(programme_evidence,holdings_path)
        measured = collect(holdings_path,programme_evidence,target_quarter,set(cohort),
                           evidence=evidence,pair_cache=programme_pair_cache)
        from pipeline.legacy_acceptance_inputs import bound_legacy_inputs
        bound=bound_legacy_inputs(evidence,holdings_path,set(cohort),result['inputs'])
        extend_acceptance(result,measured,thresholds_path=programme_thresholds,bound_legacy_inputs=bound)
        result["inputs"]["programme_evidence"] = str(programme_evidence)
    return result


def extend_acceptance(result, observations, *, thresholds_path=None,bound_legacy_inputs=None):
    """Evaluate all working extension rows here, retaining the v3 comparison.

    This is the same acceptance mechanism used by re-attestation. Explicit
    candidate evidence enables a staged amendment without silently adopting new
    denominators/floors in the existing signed-quarter contract.
    """
    from pipeline.programme.core import ContractError, sha
    path=Path(thresholds_path or config.REFERENCE_DIR / "quarter_acceptance_programme_thresholds.json")
    spec=load_thresholds(path)
    required={row["id"] for row in spec["checks"]}
    if len(required)!=len(spec["checks"]) or set(observations)-required:
        raise ContractError("Duplicate or unknown extended acceptance metrics")
    result["v3_history"]={key:result[key] for key in ("verdict","checks","thresholds_version","calibration")}
    checks=[dict(row,status="PASS" if row["pass"] else "FAIL")
            for row in result["checks"] if row["id"]!="fund_coverage"]
    dependencies={"reconcile_rate":{"ledger"},"flagged_fv_share":{"ledger"},
        "source_blocking_fv_share":{"queue","findings_ledger"},
        "verified_fv_share":{"ledger","queue","findings_ledger"},
        "promoted_rule_drift":{"audit"},"promoted_rule_health":{"audit","admission"},
        "over_inclusion_fv_share":{"ledger"},"unfinished_investigations":{"investigate"},
        "outstanding_findings":{"findings_ledger"}}
    if bound_legacy_inputs is not None:
        for check in checks:
            missing=dependencies.get(check["id"],set())-bound_legacy_inputs
            if missing:
                check.update(status="UNASSESSABLE",**{"pass":False},
                    reason="Inputs not bound to candidate: "+", ".join(sorted(missing)))
    for row in spec["checks"]:
        observed=observations.get(row["id"],{})
        actual=_numeric(observed.get("actual"))
        threshold=_numeric(row["value"])
        assessable=bool(observed.get("assessable")) and actual is not None and threshold is not None
        exact_failure=observed.get("exact_failure") is True
        passed=bool(not exact_failure and assessable and _OPS[row["op"]](actual,threshold))
        checks.append(dict(id=row["id"],metric=row["id"],op=row["op"],value=row["value"],
            actual=actual,**{"pass":passed},status="PASS" if passed else "FAIL" if assessable or exact_failure else "UNASSESSABLE",
            reason=observed.get("reason") or ("Threshold amendment pending" if threshold is None
                else "Collector absent or evidence unavailable" if not assessable else "Compared with working bar"),
            details=observed.get("details",{})))
    states={row["status"] for row in checks}
    result.update(checks=checks,thresholds_version=spec["version"],calibration=spec["calibration"],
        verdict="FAIL" if "FAIL" in states else "UNASSESSABLE" if "UNASSESSABLE" in states else "PASS",
        unassessable_checks=[row["id"] for row in checks if row["status"]=="UNASSESSABLE"],
        programme_thresholds_sha256=sha(path),readiness="blocked" if states!={"PASS"} else "data_gates_pass",
        release_approval="not_granted")
    return result


def write_acceptance(
    result: dict[str, Any],
    *,
    json_path: Path | None = None,
    funds_path: Path | None = None,
) -> tuple[Path, Path]:
    json_path = json_path or config.QUARTER_ACCEPTANCE_FILE
    funds_path = funds_path or config.QUARTER_ACCEPTANCE_FUNDS_FILE
    funds = result.get("_funds", [])
    result = {key:value for key,value in result.items() if key!="_funds"}
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
    parser.add_argument("--admission", type=Path, default=None,
                        help="Input admission audit; default = sibling of --audit.")
    parser.add_argument("--holdings", type=Path, default=None)
    parser.add_argument("--thresholds", type=Path, default=None)
    parser.add_argument("--investigate-dir", type=Path, default=None)
    parser.add_argument("--findings-ledger", type=Path, default=None,
                        help="Findings lifecycle ledger; default = agent_b2/findings_ledger.csv.")
    parser.add_argument("--programme-evidence", type=Path, default=None)
    parser.add_argument("--programme-thresholds", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help="JSON output path override.")
    parser.add_argument("--funds-out", type=Path, default=None, help="Funds CSV path override.")
    args = parser.parse_args(argv)

    result = compute_acceptance(
        target_quarter=args.quarter,
        ledger_path=args.ledger,
        queue_path=args.queue,
        audit_path=args.audit,
        admission_path=args.admission,
        holdings_path=args.holdings,
        thresholds_path=args.thresholds,
        investigate_dir=args.investigate_dir,
        findings_ledger_path=args.findings_ledger,
        programme_evidence=args.programme_evidence,
        programme_thresholds=args.programme_thresholds,
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
