"""Bridge from CIK-quarter fix targets to the B1 -> B2 reviewed workflow.

This module keeps the operator from dispatching B2 remediation directly from raw
residual rows. It maps a target worklist (cik,target_quarter) to B1 review IDs in
the unified review queue, builds the B1 batch, and leaves the B2 batch to be
derived from B1 verdicts.

No workers are launched here. This is deterministic, cache-only, and writes only
under the normal Agent B batch directory via ``scripts.agent_b.run_review``.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable

from pipeline import config
from pipeline.bdc_cik_review import normalize_cik, normalize_text, read_csv_rows
from scripts.agent_b import run_review

DEFAULT_QUEUE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"
DEFAULT_B1_BASE = config.OUTPUT_DIR / "agent_b"


class ReviewedWorkflowError(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise ReviewedWorkflowError(f"missing targets CSV: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ReviewedWorkflowError(f"empty targets CSV: {path}")
    return rows


def _field(row: dict, names: Iterable[str]) -> str:
    for name in names:
        value = normalize_text(row.get(name))
        if value:
            return value
    return ""


def _rank(row: dict) -> int:
    try:
        return int(float(normalize_text(row.get("priority_rank")) or "0"))
    except ValueError:
        return 0


def _target_rows(path: Path, *, limit: int | None = None) -> list[dict]:
    rows = _read_csv(path)
    if limit is not None:
        rows = rows[:limit]
    targets: list[dict] = []
    for idx, row in enumerate(rows, start=1):
        review_id = _field(row, ("review_id", "ReviewId", "reviewID"))
        cik = normalize_cik(_field(row, ("cik", "Cik", "CIK")))
        report_date = _field(row, ("target_quarter", "TargetQuarter", "report_date", "ReportDate"))
        if not review_id and not (cik and report_date):
            raise ReviewedWorkflowError(
                f"target row {idx} needs review_id or cik plus target_quarter/report_date"
            )
        targets.append({"row_number": idx, "review_id": review_id, "cik": cik, "report_date": report_date})
    return targets


def select_review_rows(
    *,
    targets_path: Path,
    queue_path: Path = DEFAULT_QUEUE,
    lane: str = "blocker",
    engines: set[str] | None = None,
    rule_names: set[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return prioritized review queue rows matching target review IDs or CIK-quarters."""

    if not queue_path.exists():
        raise ReviewedWorkflowError(f"missing review queue: {queue_path}")
    targets = _target_rows(targets_path, limit=limit)
    queue_rows = read_csv_rows(queue_path)
    queue_by_id = {normalize_text(r.get("review_id")): r for r in queue_rows}
    selected: dict[str, dict] = {}
    missing: list[str] = []

    lane_norm = normalize_text(lane)
    engines_norm = {normalize_text(e) for e in (engines or {"conservation"})}
    rules_norm = {normalize_text(r) for r in (rule_names or {"fv_conservation"})}

    for target in targets:
        if target["review_id"]:
            row = queue_by_id.get(target["review_id"])
            if row is None:
                missing.append(f"row {target['row_number']}: review_id={target['review_id']}")
                continue
            matches = [row]
        else:
            matches = []
            for row in queue_rows:
                if lane_norm and normalize_text(row.get("lane")) != lane_norm:
                    continue
                if engines_norm and normalize_text(row.get("engine")) not in engines_norm:
                    continue
                if rules_norm and normalize_text(row.get("rule_name")) not in rules_norm:
                    continue
                if normalize_cik(row.get("cik")) != target["cik"]:
                    continue
                if normalize_text(row.get("report_date")) != target["report_date"]:
                    continue
                matches.append(row)
            if not matches:
                missing.append(
                    f"row {target['row_number']}: cik={target['cik']} report_date={target['report_date']}"
                )
                continue

        for row in sorted(matches, key=_rank):
            rid = normalize_text(row.get("review_id"))
            if rid:
                selected.setdefault(rid, row)

    if missing:
        raise ReviewedWorkflowError(
            "no B1 review queue row matched: " + "; ".join(missing)
        )
    if not selected:
        raise ReviewedWorkflowError("no B1 review IDs selected")
    return sorted(selected.values(), key=_rank)


def build_b1_batch(
    batch_id: str,
    *,
    targets_path: Path,
    queue_path: Path = DEFAULT_QUEUE,
    base_dir: Path = DEFAULT_B1_BASE,
    lane: str = "blocker",
    engines: set[str] | None = None,
    rule_names: set[str] | None = None,
    limit: int | None = None,
) -> dict:
    selected = select_review_rows(
        targets_path=targets_path,
        queue_path=queue_path,
        lane=lane,
        engines=engines,
        rule_names=rule_names,
        limit=limit,
    )
    review_ids = {normalize_text(r.get("review_id")) for r in selected}
    result = run_review.discover(
        batch_id,
        base_dir=base_dir,
        queue_path=queue_path,
        review_ids=review_ids,
    )

    batch_dir = base_dir / "batch" / batch_id
    selection_path = batch_dir / "selected_review_ids.csv"
    with open(selection_path, "w", newline="", encoding="utf-8") as f:
        cols = ["review_id", "priority_rank", "cik", "report_date", "engine", "rule_name", "lane"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in selected:
            w.writerow({c: normalize_text(row.get(c)) for c in cols})

    return {
        "b1_batch_id": batch_id,
        "n_review_ids": len(review_ids),
        "worklist": result["worklist"],
        "selected_review_ids": str(selection_path),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a B1 batch from CIK-quarter B2 targets.")
    sub = parser.add_subparsers(dest="mode", required=True)
    b = sub.add_parser("build-b1-batch")
    b.add_argument("batch_id")
    b.add_argument("--targets", type=Path, required=True,
                   help="CSV with review_id or cik,target_quarter/report_date columns.")
    b.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    b.add_argument("--base-dir", type=Path, default=DEFAULT_B1_BASE)
    b.add_argument("--lane", default="blocker")
    b.add_argument("--engine", action="append", default=None,
                   help="Review queue engine to match. Repeatable. Default: conservation.")
    b.add_argument("--rule-name", action="append", default=None,
                   help="Review queue rule_name to match. Repeatable. Default: fv_conservation.")
    b.add_argument("--limit", type=int, default=None)

    args = parser.parse_args(argv)
    try:
        if args.mode == "build-b1-batch":
            result = build_b1_batch(
                args.batch_id,
                targets_path=args.targets,
                queue_path=args.queue,
                base_dir=args.base_dir,
                lane=args.lane,
                engines=set(args.engine or ["conservation"]),
                rule_names=set(args.rule_name or ["fv_conservation"]),
                limit=args.limit,
            )
            print(json.dumps(result, indent=2))
            return 0
    except ReviewedWorkflowError as exc:
        print(f"PRECHECK_FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
