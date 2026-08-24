"""Machine-checked readiness gate for a quarter pass (the Q4 archaeology, mechanized).

Runs as the FIRST stage of ``run_quarter_pass`` (exit 1 halts the pass) and
standalone as a probe: ``python -m scripts.pass_preflight --quarter 2026-03-31``.
Every check encodes a measured Q4 2025 incident:

  applier_coverage (hard)    121/143 B2 packets dispatched against appliers that
                             did not exist -- every fix_class implied by the
                             actionable pool must have a registered applier or a
                             policy/rule-track route.
  anchor_assessability (hard) 2026-03-31 needed manual companyfacts cache surgery
                             to become assessable; below the assessability min the
                             check lists lagging cohort CIKs + the refresh command.
                             NO network calls -- report only.
  rule_hygiene (hard)        Q1's earlier battery failed drift/health on
                             pre-existing noop rules; any live rule not status=ok
                             or with drift fails BEFORE hours of battery burn.
  stale_staged (warn)        staged-but-ungated leaves predate the pass.
  readjudication_worklist (warn) wrong-diagnosis refusals awaiting B1 re-dispatch.
  competing_processes        codex = hard (single-dispatcher rule); python/pytest
                             (excluding self) = warn.

``--strict`` promotes warns to hard. Exit 0 READY / 1 NOT_READY. Artifact JSON
mirrors the acceptance shape. ASCII-only output. Cache-only; never fetches.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_OUT = config.OUTPUT_DIR / "pass_preflight.json"
DEFAULT_SHADOW_LEDGER = config.OUTPUT_DIR / "shadow" / "validation_results_ledger.csv"
DEFAULT_AUDIT = config.OUTPUT_DIR / "agent_fix_application_audit.csv"
DEFAULT_STAGED = config.OUTPUT_DIR / "agent_b2" / "corrections"
DEFAULT_INVESTIGATE = config.OUTPUT_DIR / "agent_investigate"
DEFAULT_COMPANYFACTS_CACHE = config.DATA_DIR / "raw" / "companyfacts_cache"


def _check(check_id: str, severity: str, ok: bool, detail: str,
           items: list | None = None) -> dict[str, Any]:
    return {"id": check_id, "severity": severity, "pass": bool(ok),
            "detail": detail, "items": items or []}


# ------------------------------------------------------------ 1. applier coverage

def check_applier_coverage(ledger_rows: list[dict], verdict_dirs) -> dict[str, Any]:
    """Every fix_class implied by the actionable pool has an applier or a
    policy/rule-track route (the 121/143 unimplemented-applier lesson)."""
    from pipeline.agent_b2_appliers import POST_STAGING_APPLIERS
    from scripts.agent_b2.run_remediation import (
        MECHANISM_TO_FIX_CLASS, POLICY_FIX_CLASSES, RULE_TRACK_FIX_CLASSES,
        WRAPPER_PATCH_APPLIERS)
    covered = (set(POST_STAGING_APPLIERS) | set(WRAPPER_PATCH_APPLIERS)
               | set(POLICY_FIX_CLASSES) | set(RULE_TRACK_FIX_CLASSES))
    uncovered: dict[str, list[str]] = {}
    for row in ledger_rows:
        if row.get("state") not in ("real_error_unremediated", "remediation_pulled"):
            continue
        rid = row.get("review_id", "")
        verdict = None
        for vdir in verdict_dirs:
            p = Path(vdir) / f"{rid}.json"
            if p.exists():
                try:
                    verdict = json.loads(p.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    verdict = None
                break
        if verdict is None:
            continue
        fcs = [str(f.get("fix_class") or "") for f in (verdict.get("findings") or [])]
        if not any(fcs):
            mapped = MECHANISM_TO_FIX_CLASS.get(str(verdict.get("mechanism") or ""))
            fcs = [mapped] if mapped else []
        for fc in fcs:
            if fc and fc not in covered:
                uncovered.setdefault(fc, []).append(rid)
    items = [{"fix_class": fc, "n_findings": len(rids), "example_review_ids": rids[:5]}
             for fc, rids in sorted(uncovered.items())]
    ok = not uncovered
    detail = ("all actionable fix classes covered" if ok else
              f"{len(uncovered)} fix class(es) without an applier or policy route: "
              + ", ".join(sorted(uncovered)))
    return _check("applier_coverage", "hard", ok, detail, items)


# ------------------------------------------------------ 2. anchor assessability

def check_anchor_assessability(quarter: str, *, shadow_ledger: Path = DEFAULT_SHADOW_LEDGER,
                               manifest_path: Path | None = None,
                               cache_dir: Path = DEFAULT_COMPANYFACTS_CACHE,
                               min_pct: float | None = None) -> dict[str, Any]:
    from pipeline.quarter_acceptance import load_cohort, load_thresholds
    cohort = load_cohort(manifest_path)
    if min_pct is None:
        min_pct = float(load_thresholds().get("assessability", {}).get("min", 50.0))
    status: dict[str, str] = {}
    if Path(shadow_ledger).exists():
        with Path(shadow_ledger).open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("engine") == "conservation"
                        and row.get("rule_name") == "fv_conservation"
                        and row.get("period") == quarter):
                    cik = str(row.get("cik") or "").zfill(10)
                    if cik in cohort:
                        status[cik] = str(row.get("status") or "")
    n_pass = sum(1 for s in status.values() if s == "pass")
    n_fail = sum(1 for s in status.values() if s == "fail")
    n_skip = sum(1 for s in status.values() if s == "skip")
    denom = n_pass + n_fail + n_skip
    rate = round(100.0 * (n_pass + n_fail) / denom, 3) if denom else 0.0
    ok = rate >= min_pct
    lagging = []
    if not ok:
        now = datetime.now(timezone.utc)
        for cik in sorted(cohort):
            s = status.get(cik, "no_ledger_row")
            if s in ("skip", "no_ledger_row"):
                cache = Path(cache_dir) / f"{cik}.json"
                age_days = None
                if cache.exists():
                    age_days = round((now - datetime.fromtimestamp(
                        cache.stat().st_mtime, tz=timezone.utc)).days, 1)
                lagging.append({"cik": cik, "status": s,
                                "companyfacts_cached": cache.exists(),
                                "cache_age_days": age_days})
    detail = (f"anchored_rate {rate} vs min {min_pct} "
              f"(pass {n_pass} / fail {n_fail} / skip {n_skip})")
    if not ok and lagging:
        ciks = " ".join(x["cik"] for x in lagging[:80])
        detail += ("; remedy (operator, network): python -m scripts.refresh_companyfacts "
                   f"--quarter {quarter} --ciks {ciks}")
    return _check("anchor_assessability", "hard", ok, detail, lagging)


# ------------------------------------------------------------- 3. rule hygiene

def check_rule_hygiene(audit_path: Path = DEFAULT_AUDIT) -> dict[str, Any]:
    if not Path(audit_path).exists():
        return _check("rule_hygiene", "hard", False,
                      f"fix-application audit missing: {audit_path} (run a rebuild first)")
    bad = []
    with Path(audit_path).open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            status, drift = str(row.get("status") or ""), str(row.get("drift") or "")
            if status != "ok" or drift:
                bad.append({"rule_id": row.get("rule_id", ""), "cik": row.get("cik", ""),
                            "status": status, "drift": drift})
    ok = not bad
    detail = ("all live rules ok, zero drift" if ok else
              f"{len(bad)} live rule(s) noop/error/drift -- retire or re-key before the pass "
              "(archive to a _pulled_<reason>_<date>/ dir with README)")
    return _check("rule_hygiene", "hard", ok, detail, bad)


# ------------------------------------------------------------ 4. stale staged

def check_stale_staged(staged_dir: Path = DEFAULT_STAGED,
                       investigate_dir: Path = DEFAULT_INVESTIGATE) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    items = []
    if Path(staged_dir).exists():
        for p in sorted(Path(staged_dir).rglob("*.json")):
            age = round((now - datetime.fromtimestamp(
                p.stat().st_mtime, tz=timezone.utc)).days, 1)
            items.append({"leaf": str(p.relative_to(staged_dir)),
                          "store": "agent_b2/corrections", "age_days": age})
    if Path(investigate_dir).exists():
        for cik_dir in sorted(Path(investigate_dir).iterdir()):
            rules = cik_dir / "rules"
            if cik_dir.name.startswith("_") or not rules.is_dir():
                continue
            for p in sorted(rules.glob("*.json")):
                age = round((now - datetime.fromtimestamp(
                    p.stat().st_mtime, tz=timezone.utc)).days, 1)
                items.append({"leaf": f"{cik_dir.name}/rules/{p.name}",
                              "store": "agent_investigate", "age_days": age})
    ok = not items
    detail = ("no stale staged corrections/proposals" if ok else
              f"{len(items)} staged leaf(s)/proposal(s) awaiting gate or archive")
    return _check("stale_staged", "warn", ok, detail, items)


# ------------------------------------------------- 5. re-adjudication worklist

def check_readjudication(worklist_path: Path | None = None) -> dict[str, Any]:
    from scripts.agent_b2.run_remediation import READJUDICATION_WORKLIST
    p = Path(worklist_path or READJUDICATION_WORKLIST)
    n = 0
    if p.exists():
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            n = sum(1 for _ in csv.DictReader(f))
    ok = n == 0
    detail = ("re-adjudication worklist empty" if ok else
              f"{n} wrong-diagnosis finding(s) awaiting B1 re-dispatch ({p})")
    return _check("readjudication_worklist", "warn", ok, detail)


# ------------------------------------------------------ 6. competing processes

def _tasklist() -> str:
    return subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True,
                          text=True, timeout=30).stdout


def check_competing_processes(tasklist_fn: Callable[[], str] = _tasklist) -> list[dict[str, Any]]:
    """Two checks: codex (hard -- single-dispatcher rule) and python/pytest (warn)."""
    codex, pythons = [], []
    self_pid = str(os.getpid())
    try:
        reader = csv.reader(tasklist_fn().splitlines())
        for row in reader:
            if len(row) < 2 or row[0] == "Image Name":
                continue
            name, pid = row[0].lower(), row[1]
            if "codex" in name:
                codex.append({"image": row[0], "pid": pid})
            elif ("python" in name or "pytest" in name) and pid != self_pid:
                pythons.append({"image": row[0], "pid": pid})
    except (OSError, subprocess.SubprocessError) as exc:
        return [_check("codex_processes", "hard", False, f"tasklist failed: {exc}")]
    return [
        _check("codex_processes", "hard", not codex,
               "no codex processes" if not codex else
               f"{len(codex)} codex process(es) running -- single-dispatcher rule",
               codex),
        _check("python_processes", "warn", not pythons,
               "no other python/pytest processes" if not pythons else
               f"{len(pythons)} other python/pytest process(es) running", pythons),
    ]


# ----------------------------------------------------------------------- drive

def run_preflight(quarter: str, *, strict: bool = False,
                  checks: list[dict] | None = None) -> dict[str, Any]:
    """Assemble the artifact from computed (or injected, for tests) checks."""
    if checks is None:
        from scripts import findings_ledger as fl
        from scripts.check_tier_coverage import VERDICT_DIRS
        ledger_rows = fl.build_ledger()
        checks = [
            check_applier_coverage(ledger_rows, VERDICT_DIRS),
            check_anchor_assessability(quarter),
            check_rule_hygiene(),
            check_stale_staged(),
            check_readjudication(),
            *check_competing_processes(),
        ]
    hard_fail = [c for c in checks if not c["pass"] and c["severity"] == "hard"]
    warn_fail = [c for c in checks if not c["pass"] and c["severity"] == "warn"]
    not_ready = bool(hard_fail) or (strict and bool(warn_fail))
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_quarter": quarter,
        "strict": strict,
        "verdict": "NOT_READY" if not_ready else "READY",
        "n_hard_fail": len(hard_fail),
        "n_warn": len(warn_fail),
        "checks": checks,
    }


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Machine-checked quarter-pass readiness gate.")
    ap.add_argument("--quarter", required=True, help="target report_date YYYY-MM-DD")
    ap.add_argument("--strict", action="store_true", help="promote warns to hard")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    result = run_preflight(args.quarter, strict=args.strict)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("preflight %s: %s (%d hard fail, %d warn) -> %s",
                args.quarter, result["verdict"], result["n_hard_fail"],
                result["n_warn"], args.out)
    for c in result["checks"]:
        tag = "PASS" if c["pass"] else ("FAIL" if c["severity"] == "hard" else "WARN")
        logger.info("  [%s] %-24s %s", tag, c["id"], c["detail"])
        for item in c["items"][:15]:
            logger.info("      %s", json.dumps(item))
        if len(c["items"]) > 15:
            logger.info("      ... and %d more", len(c["items"]) - 15)
    return 1 if result["verdict"] == "NOT_READY" else 0


if __name__ == "__main__":
    sys.exit(main())
