"""Fleet acceptance: evaluate one B2 fleet batch against the pre-declared criteria.

Mechanizes the round-4 acceptance bars (data_investigation_results.md 2026-08-20)
the same way ``pipeline.quarter_acceptance`` mechanizes the quarter contract:
thresholds are DATA (data/reference/fleet_acceptance_thresholds.json), the verdict
is computed from batch artifacts the workers cannot edit (gate JSONL logs,
validate.txt files, archive dirs), and the artifact is written next to the batch
outputs as ``data/output/agent_b2/fleet_acceptance_<batch_id>.json``.

ADVISORY at ship: the thresholds file's ``enforce`` flags are false, so promotion
proceeds regardless of the verdict and the operator reads the artifact. Flipping
``enforce.promote_requires_pass`` / ``enforce.resume_requires_audit`` to true (a
data edit, no deploy) makes ``promote_passes`` and the quarter-pass resume refuse
without a PASS / audit artifact.

Exit codes mirror quarter_acceptance: 0 PASS, 1 FAIL, 2 NOT_ASSESSABLE (no gate
log entries for the batch -- nothing was gated, nothing to accept). ASCII-only.

Usage:
  python -m scripts.fleet_acceptance --batch-id q1b2r1
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402
from scripts import b2_run_metrics as bm  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = config.REFERENCE_DIR / "fleet_acceptance_thresholds.json"
DEFAULT_BATCH_ROOT = config.OUTPUT_DIR / "agent_b2" / "batch"
DEFAULT_ARCHIVE_ROOT = config.OUTPUT_DIR / "agent_b2" / "corrections_archive"
DEFAULT_AUDIT_DIR = config.OUTPUT_DIR / "agent_b2"

# Wrong-diagnosis refusal category emitted by b2_run_metrics.categorize_reason.
_DIAGNOSIS_REFUSAL_CATEGORY = "defect_signature_refusal"
_SELECTOR_NOOP_CATEGORIES = {"selector_noop", "selector_noop_stale"}
_REPLAY_OFFSCOPE_CHECKS = {"replay_equivalence", "off_scope_invariance"}

_OPS = {
    ">=": lambda a, v: a >= v,
    "<=": lambda a, v: a <= v,
    ">": lambda a, v: a > v,
    "<": lambda a, v: a < v,
    "==": lambda a, v: a == v,
}


def load_thresholds(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_THRESHOLDS
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _resolve_metric(metrics: dict[str, Any], dotted: str) -> Any:
    node: Any = metrics
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def build_metrics(
    batch_id: str,
    *,
    batch_root: Path | None = None,
    archive_root: Path | None = None,
    audit_dir: Path | None = None,
    known_tokens: list[str] | None = None,
) -> dict[str, Any]:
    """Batch metrics (via b2_run_metrics) + the derived fleet-acceptance metrics."""
    batch_root = Path(batch_root or DEFAULT_BATCH_ROOT)
    archive_root = Path(archive_root or DEFAULT_ARCHIVE_ROOT)
    audit_dir = Path(audit_dir or DEFAULT_AUDIT_DIR)
    known_tokens = known_tokens or []

    batch_rows = bm.rows_for_batch(batch_root / batch_id, batch_id)
    batch: dict[str, Any] = {}
    for r in batch_rows:
        # first write wins for duplicate names (manifest_wave_rows repeats per wave)
        batch.setdefault(r["metric"], r["value"])

    def _sum_suffix(kind: str, names: set[str]) -> int:
        total = 0
        for r in batch_rows:
            m = r["metric"]
            if kind not in m:
                continue
            suffix = m.split(kind, 1)[1]
            if suffix in names:
                try:
                    total += int(r["value"])
                except (TypeError, ValueError):
                    continue
        return total

    n_entries = sum(
        int(r["value"]) for r in batch_rows
        if r["metric"].endswith("_entries") and "unparseable" not in r["metric"]
    )
    n_diag = _sum_suffix("_refusal__", {_DIAGNOSIS_REFUSAL_CATEGORY})

    archive_dirs = []
    if archive_root.exists():
        archive_dirs = [d.name for d in archive_root.iterdir()
                        if d.is_dir() and d.name.startswith((batch_id, f"promoted_{batch_id}"))]
    pull_dirs = [n for n in archive_dirs
                 if "pull" in n.lower() or "reverted" in n.lower()]
    unknown_dirs = [n for n in archive_dirs
                    if not any(tok.lower() in n.lower() for tok in known_tokens)
                    and not n.startswith(f"promoted_{batch_id}")]

    audit_artifact = audit_dir / f"replay_live_stats_{batch_id}.json"

    derived = {
        "selector_noop_refusals": _sum_suffix("_refusal__", _SELECTOR_NOOP_CATEGORIES),
        "replay_offscope_failures": _sum_suffix("_check_fail__", _REPLAY_OFFSCOPE_CHECKS),
        "post_promotion_pull_dirs": len(pull_dirs),
        "post_promotion_pull_dir_names": "; ".join(sorted(pull_dirs)),
        "post_promotion_audit_present": 1 if audit_artifact.exists() else 0,
        "post_promotion_audit_path": str(audit_artifact),
        "unknown_archive_dirs": len(unknown_dirs),
        "unknown_archive_dir_names": "; ".join(sorted(unknown_dirs)),
        "gated_entries": n_entries,
        "defect_signature_refusal_pct": (
            round(100.0 * n_diag / n_entries, 1) if n_entries else 0.0
        ),
    }
    return {"batch": batch, "derived": derived}


def evaluate(batch_id: str, metrics: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    checks = []
    all_pass = True
    for spec in thresholds.get("checks", []):
        actual = _resolve_metric(metrics, spec["metric"])
        op = spec["op"]
        try:
            ok = bool(_OPS[op](float(actual), float(spec["value"]))) \
                if actual is not None and op in _OPS else False
        except (TypeError, ValueError):
            ok = False
        all_pass = all_pass and ok
        checks.append({"id": spec.get("id", spec["metric"]), "metric": spec["metric"],
                       "op": op, "value": spec["value"], "actual": actual, "pass": ok})
    verdict = "PASS" if (all_pass and checks) else "FAIL"
    if not metrics["derived"].get("gated_entries"):
        verdict = "NOT_ASSESSABLE"  # nothing was gated for this batch
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "batch_id": batch_id,
        "thresholds_version": thresholds.get("version"),
        "calibration": thresholds.get("calibration", "provisional"),
        "enforce": thresholds.get("enforce", {}),
        "verdict": verdict,
        "checks": checks,
        "metrics": metrics,
    }


def acceptance_artifact_path(batch_id: str, out_dir: Path | None = None) -> Path:
    return Path(out_dir or DEFAULT_AUDIT_DIR) / f"fleet_acceptance_{batch_id}.json"


def write_acceptance(result: dict[str, Any], out_path: Path | None = None) -> Path:
    p = out_path or acceptance_artifact_path(result["batch_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return p


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Evaluate one B2 fleet batch against the "
                                             "pre-declared acceptance criteria.")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--thresholds", type=Path, default=None)
    ap.add_argument("--batch-root", type=Path, default=None)
    ap.add_argument("--archive-root", type=Path, default=None)
    ap.add_argument("--audit-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    thresholds = load_thresholds(args.thresholds)
    metrics = build_metrics(args.batch_id, batch_root=args.batch_root,
                            archive_root=args.archive_root, audit_dir=args.audit_dir,
                            known_tokens=thresholds.get("known_archive_reason_tokens", []))
    result = evaluate(args.batch_id, metrics, thresholds)
    out = write_acceptance(result, args.out or (
        acceptance_artifact_path(args.batch_id, args.audit_dir)))
    logger.info("fleet %s acceptance: %s (calibration=%s, enforce=%s)",
                args.batch_id, result["verdict"], result["calibration"],
                result["enforce"])
    for c in result["checks"]:
        logger.info("  [%s] %-26s %s %s %s (actual %s)",
                    "PASS" if c["pass"] else "FAIL", c["id"], c["metric"], c["op"],
                    c["value"], c["actual"])
    logger.info("wrote %s", out)
    return {"PASS": 0, "FAIL": 1}.get(result["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
