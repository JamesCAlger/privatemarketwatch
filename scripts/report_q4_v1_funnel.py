"""Build the canonical Q4-2025 v1 closure ledger and 70-fund funnel.

This is an internal, cache-only report. It retains the frozen q4final population
while overlaying the current review queue, verdict stores, and B2 provenance. A
worklist entry is dispatch evidence only; it never becomes a remediation result.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline import config
from scripts import findings_ledger as fl


QUARTER = "2025-12-31"
EXCEPTION_STATES = {"needs_human", "evidence_backlog"}
FIELDS = [
    "cik", "fund", "shadow_rules_fired", "b1_adjudicated", "b1_real_error",
    "b1_false_alarm", "b1_ambiguous", "b1_real_error_with_fix_class",
    "b1_route_missing", "b2_worklist_seen", "b2_authored_leaf_seen",
    "b2_validated_no_change", "b3_gate_pass_seen", "b2_promoted_seen",
    "actionable_outstanding", "declared_exceptions",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _ids_from_leaves(root: Path) -> set[str]:
    ids: set[str] = set()
    if not root.exists():
        return ids
    for path in root.rglob("*.json"):
        if path.name.endswith(".escalation.json"):
            continue
        try:
            leaf = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(leaf, dict):
            ids.update(str(item) for item in leaf.get("source_review_ids") or [] if str(item))
    return ids


def _worklist_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    if not root.exists():
        return ids
    for path in root.rglob("worklist.csv"):
        for row in _read_csv(path):
            ids.update(item.strip() for item in str(row.get("source_review_ids") or "").split(";")
                       if item.strip())
    return ids


def _keyed_json_ids(root: Path, key: str, *, predicate=None) -> set[str]:
    """Read only records that explicitly identify their source review IDs."""
    ids: set[str] = set()
    if not root.exists():
        return ids
    for path in root.rglob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or (predicate is not None and not predicate(raw)):
            continue
        ids.update(str(x) for x in raw.get(key) or [] if str(x))
    return ids


def _disposition_ids(root: Path) -> set[str]:
    return _keyed_json_ids(
        root, "source_review_ids",
        predicate=lambda x: x.get("schema_version") == 1
        and x.get("disposition") == "no_change_required"
        and x.get("reason_code") == "baseline_source_identity_present",
    )


def _gate_pass_ids(root: Path) -> set[str]:
    return _keyed_json_ids(
        root, "source_review_ids",
        predicate=lambda x: x.get("verdict") == "PASS" and bool(x.get("batch_id")),
    )


def _verdicts(verdicts_dirs: tuple[Path, ...]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for verdicts_dir in verdicts_dirs:
        if not verdicts_dir.exists():
            continue
        for path in verdicts_dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            out.setdefault(str(raw.get("review_id") or path.stem), raw)
    return out


def build_report(*, frozen_ledger_path: Path, queue_path: Path, manifest_path: Path,
                 verdicts_dirs: tuple[Path, ...], b2_batch_dir: Path, b2_corrections_dir: Path,
                 promoted_dir: Path) -> tuple[list[dict], list[dict], dict[str, object]]:
    """Return (lifecycle rows, per-fund report, summary) with exact-ID evidence only."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    cohort = {str(e["cik"]).zfill(10): str(e.get("entity_name") or "")
              for e in manifest["entries"]}
    lifecycle = fl.build_ledger(
        queue_path=queue_path, seed_paths=(frozen_ledger_path,), quarter=QUARTER,
        manifest_path=manifest_path, closure_mode=True, verdict_dirs=verdicts_dirs,
    )
    verdicts = _verdicts(verdicts_dirs)
    worklisted = _worklist_ids(b2_batch_dir)
    authored = _ids_from_leaves(b2_corrections_dir)
    promoted = _ids_from_leaves(promoted_dir)
    no_change = _disposition_ids(b2_batch_dir)
    gate_pass = _gate_pass_ids(b2_batch_dir)

    for row in lifecycle:
        rid = row["review_id"]
        row["b2_worklist_seen"] = rid in worklisted
        row["b2_authored_leaf_seen"] = rid in authored
        row["b2_promoted_seen"] = rid in promoted
        row["b2_validated_no_change"] = rid in no_change
        row["b3_gate_pass_seen"] = rid in gate_pass
        if rid in no_change:
            row["state"] = "b1_re_adjudication_required"
        elif row["state"] == "remediation_staged" and rid in gate_pass:
            row["state"] = "b3_pass_pending_promotion"
        elif row["state"] == "real_error_unremediated" and rid in worklisted:
            row["state"] = "b2_execution_unproven"

    counts = fl.summarize(lifecycle, closure_mode=True)
    report: list[dict] = []
    for cik, fund in sorted(cohort.items()):
        rows = [r for r in lifecycle if str(r.get("cik") or "").zfill(10) == cik]
        adjudicated = [r for r in rows if r["review_id"] in verdicts]
        real = [r for r in adjudicated if verdicts[r["review_id"]].get("verdict") == "real_error"]
        fixable = [r for r in real if bool(r.get("has_fix_route"))]
        report.append({
            "cik": cik, "fund": fund, "shadow_rules_fired": len(rows),
            "b1_adjudicated": len(adjudicated), "b1_real_error": len(real),
            "b1_false_alarm": sum(verdicts[r["review_id"]].get("verdict") == "false_alarm" for r in adjudicated),
            "b1_ambiguous": sum(verdicts[r["review_id"]].get("verdict") == "ambiguous" for r in adjudicated),
            "b1_real_error_with_fix_class": len(fixable),
            "b1_route_missing": sum(r["state"] == "b1_route_missing" for r in rows),
            "b2_worklist_seen": sum(bool(r["b2_worklist_seen"]) for r in rows),
            "b2_authored_leaf_seen": sum(bool(r["b2_authored_leaf_seen"]) for r in rows),
            "b2_validated_no_change": sum(bool(r["b2_validated_no_change"]) for r in rows),
            "b3_gate_pass_seen": sum(bool(r["b3_gate_pass_seen"]) for r in rows),
            "b2_promoted_seen": sum(bool(r["b2_promoted_seen"]) for r in rows),
            "actionable_outstanding": sum(r["state"] in fl.CLOSURE_ACTIONABLE_STATES for r in rows),
            "declared_exceptions": sum(r["state"] in EXCEPTION_STATES for r in rows),
        })
    summary = {
        "quarter": QUARTER,
        "cohort_manifest": str(manifest_path),
        "frozen_population": str(frozen_ledger_path),
        "current_queue": str(queue_path),
        "closure_mode": True,
        "lifecycle": counts,
        "b2_evidence_contract": (
            "A worklist-only packet is b2_execution_unproven; an absent leaf is never "
            "a no-change result. B3 gates count only when keyed by source_review_ids."
        ),
        "totals": {field: sum(int(row[field]) for row in report)
                   for field in FIELDS if field not in {"cik", "fund"}},
    }
    return lifecycle, report, summary


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["review_id", "state"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-ledger", type=Path,
                        default=config.OUTPUT_DIR / "quarter_pass" / "q4final" / "findings_ledger_post.csv")
    parser.add_argument("--queue", type=Path,
                        default=config.OUTPUT_DIR / "review_queue" / "review_queue.csv")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    lifecycle, report, summary = build_report(
        frozen_ledger_path=args.frozen_ledger, queue_path=args.queue,
        manifest_path=config.WRAPPER_COHORT_MANIFEST_FILE,
        verdicts_dirs=(config.OUTPUT_DIR / "review_queue" / "verdicts",
                       config.OUTPUT_DIR / "bdc_cik_review" / "verdicts"),
        b2_batch_dir=config.OUTPUT_DIR / "agent_b2" / "batch",
        b2_corrections_dir=config.OUTPUT_DIR / "agent_b2" / "corrections",
        promoted_dir=config.AGENT_B2_CORRECTIONS_DIR,
    )
    _write_csv(args.output_dir / "q4_2025_v1_lifecycle.csv", lifecycle)
    _write_csv(args.output_dir / "q4_2025_v1_fund_funnel.csv", report)
    (args.output_dir / "q4_2025_v1_fund_funnel_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["lifecycle"]["dry"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
