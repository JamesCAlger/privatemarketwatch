"""Agent B1 deterministic driver (the run_quarter analog): discover + finalize.

  discover <batch_id>  -- select a sample of the flagged population from the unified
                          review queue, build bounded bundles, and write the batch
                          worklist the dispatch preflight consumes. (No LLM.)
  finalize <batch_id>  -- after the Codex workers have written verdicts, validate the
                          verdict leaves (pipeline.verdict_leaf), summarize per-rule
                          precision (Wilson), route each decided verdict, release locks.

For B1, ``finalize`` does schema + routing only -- there is NO numeric gate (a verdict
is not a fix). The deterministic re-run gate lives in B3 (built later) and runs on B2's
fixes, not on B1's verdicts. Read-only on production; writes under the batch dir.
ASCII-only messages.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from pipeline import config, verdict_leaf
from pipeline import bdc_cik_review
from pipeline.review_bundles import build_review_bundles, DEFERRED_ENGINES
from pipeline.review_queue import bdc_worklist_projection
from pipeline.bdc_cik_review import read_csv_rows, normalize_text
from scripts.agent_b import review_lock

DEFAULT_BASE = config.OUTPUT_DIR / "agent_b"
DEFAULT_QUEUE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"
DEFAULT_BUNDLES = config.OUTPUT_DIR / "review_queue" / "review_bundles"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"

WORKLIST_COLUMNS = ["review_id", "engine", "lane", "cik", "report_date", "rule_name",
                    "class_hint", "bundle_path"]

# Coarse B0.5 localization class (the verified per-rule tally is a trial by-product;
# this is the directional default used as a routing HINT only).
_CLASS3 = {"conservation", "cross_source", "gav_recon", "fund_strategy"}
_CLASS2_RULES = {"pik_le_interest_rate", "pct_of_net_assets_identity"}


def _class_hint(engine: str, rule_name: str) -> str:
    if engine in _CLASS3:
        return "class3_aggregate"
    if rule_name in _CLASS2_RULES or "identity" in rule_name:
        return "class2_within_row"
    return "class1_single_cell"


def _batch_dir(base_dir: Path, batch_id: str) -> Path:
    d = base_dir / "batch" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def discover(
    batch_id: str,
    *,
    base_dir: Path = DEFAULT_BASE,
    queue_path: Path = DEFAULT_QUEUE,
    bundles_dir: Path = DEFAULT_BUNDLES,
    lane: str | None = None,
    engines: set[str] | None = None,
    review_ids: set[str] | None = None,
    limit: int | None = None,
) -> dict:
    if not queue_path.exists():
        raise FileNotFoundError(f"missing review queue: {queue_path} (run pipeline.review_queue first)")
    rows = read_csv_rows(queue_path)

    def _keep(r: dict) -> bool:
        if lane and normalize_text(r.get("lane")) != lane:
            return False
        if engines and normalize_text(r.get("engine")) not in engines:
            return False
        if review_ids and normalize_text(r.get("review_id")) not in review_ids:
            return False
        return True

    selected = [r for r in rows if _keep(r)]  # queue is priority-ordered; honor it
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("no queue items matched the discover filters")

    batch_dir = _batch_dir(base_dir, batch_id)
    # review_bundles defers source_recon by design (its bundles come from the richer
    # bdc_cik_review generator) -- split the selection so BOTH kinds get built.
    deferred_rows = [r for r in selected if normalize_text(r.get("engine")) in DEFERRED_ENGINES]
    generic_ids = {normalize_text(r.get("review_id")) for r in selected} - {
        normalize_text(r.get("review_id")) for r in deferred_rows}
    if generic_ids:
        # Build bundles into the shared review_queue bundle dir for exactly these ids.
        build_review_bundles(
            queue_path=queue_path,
            output_dir=bundles_dir.parent,
            review_ids=generic_ids,
            overwrite=True,
        )
    if deferred_rows:
        _build_deferred_bundles(deferred_rows, bundles_dir=bundles_dir, batch_dir=batch_dir)

    worklist = []
    for r in selected:
        rid = normalize_text(r.get("review_id"))
        engine = normalize_text(r.get("engine"))
        rule = normalize_text(r.get("rule_name"))
        worklist.append({
            "review_id": rid,
            "engine": engine,
            "lane": normalize_text(r.get("lane")),
            "cik": normalize_text(r.get("cik")),
            "report_date": normalize_text(r.get("report_date")),
            "rule_name": rule,
            "class_hint": _class_hint(engine, rule),
            "bundle_path": f"{_display(bundles_dir)}/{rid}.json",
        })

    out = batch_dir / "worklist.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=WORKLIST_COLUMNS)
        w.writeheader()
        w.writerows(worklist)
    return {"batch_id": batch_id, "n_items": len(worklist), "worklist": str(out)}


def _build_deferred_bundles(rows: list[dict], *, bundles_dir: Path, batch_dir: Path) -> None:
    """Build source_recon bundles via the richer bdc_cik_review generator and place
    them in the shared bundles dir the worklist's bundle_path points at."""
    work_dir = batch_dir / "bundle_build"
    work_dir.mkdir(parents=True, exist_ok=True)
    projection = bdc_worklist_projection(items=rows)
    cols = ["review_id", "cik", "entity_name", "report_date", "mechanism",
            "affected_source_fair_value", "confidence"]
    with open(work_dir / "worklist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in projection:
            w.writerow({c: r.get(c, "") for c in cols})
    bdc_cik_review.build_bundles(output_dir=work_dir, overwrite=True)
    bundles_dir.mkdir(parents=True, exist_ok=True)
    for built in sorted((work_dir / "bundles").glob("*.json")):
        shutil.copy2(built, bundles_dir / built.name)


def _display(p: Path) -> str:
    try:
        return p.resolve().relative_to(config.PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _compare_baseline(verdicts_dir: Path, baseline_dir: Path, ids: set[str]) -> dict:
    """Agreement of the fleet's verdicts vs a baseline (e.g. the in-session trial) on the
    `verdict` field, over the shared review_ids. The M1 acceptance check."""
    def _verdict(d: Path, rid: str):
        p = d / f"{rid}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("verdict")
        except (OSError, json.JSONDecodeError):
            return None

    rows, agree, compared = [], 0, 0
    for rid in sorted(ids):
        a, b = _verdict(verdicts_dir, rid), _verdict(baseline_dir, rid)
        match = a is not None and a == b
        if a is not None and b is not None:
            compared += 1
            agree += int(match)
        rows.append({"review_id": rid, "fleet": a, "baseline": b, "match": match})
    return {"n_compared": compared, "n_agree": agree,
            "agreement": (agree / compared) if compared else None, "rows": rows}


def finalize(
    batch_id: str,
    *,
    base_dir: Path = DEFAULT_BASE,
    verdicts_dir: Path = DEFAULT_VERDICTS,
    release_locks: bool = True,
    compare_baseline: Path | None = None,
) -> dict:
    batch_dir = _batch_dir(base_dir, batch_id)
    # Wave-stamped manifests (manifest.001.json, ...) are the durable per-wave records;
    # manifest.json is only a latest-wave pointer (and the legacy single-manifest form).
    # Aggregating across waves is what makes multi-wave finalize see every dispatched
    # packet (q1p3 routed 150 of 743 off the pointer alone). Later waves win on rid
    # collision (a retry wave re-dispatches the same review_id).
    wave_paths = sorted(batch_dir.glob("manifest.[0-9][0-9][0-9].json"))
    if not wave_paths:
        wave_paths = [batch_dir / "manifest.json"]
        if not wave_paths[0].exists():
            raise FileNotFoundError(f"missing manifest: {wave_paths[0]} (run preflight first)")
    dispatch_by_id: dict[str, dict] = {}
    auto_by_id: dict[str, dict] = {}
    for path in wave_paths:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for row in manifest.get("rows", []):
            dispatch_by_id[row["review_id"]] = row
        for row in manifest.get("auto_resolved", []):
            auto_by_id[row["review_id"]] = row
    dispatch_rows = list(dispatch_by_id.values())
    auto_rows = list(auto_by_id.values())
    dispatched_ids = {r["review_id"] for r in dispatch_rows}
    auto_ids = {r["review_id"] for r in auto_rows}
    expected = dispatched_ids | auto_ids

    # The verdicts dir is shared across batches; validate only THIS batch's verdicts so a
    # sibling batch's verdicts are not flagged as "not in worklist".
    summary = verdict_leaf.validate_dir(verdicts_dir, expected_review_ids=expected,
                                        restrict_to_expected=True)

    rule_by_id = {r["review_id"]: r.get("rule_name", "?") for r in dispatch_rows}
    by_rule = defaultdict(lambda: defaultdict(int))
    routing = []
    for path in sorted(verdicts_dir.glob("*.json")):
        rid = path.stem
        if rid not in expected:
            continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        verdict = obj.get("verdict", "?")
        is_auto = bool(obj.get("auto"))
        # An ambiguous verdict where the worker could not read raw source is a coverage/
        # infra state, not a judgment that the data is unclear -- it routes to retry, NOT
        # human, and is tallied separately so it never dilutes the genuine-ambiguous count.
        no_source = (verdict == "ambiguous"
                     and obj.get("ambiguity_basis") == "source_unavailable")
        rule = rule_by_id.get(rid, "auto" if is_auto else "?")
        if not is_auto:
            by_rule[rule]["no_source" if no_source else verdict] += 1
            by_rule[rule]["_n"] += 1
        if is_auto:
            route = "coverage"
        elif no_source:
            route = "coverage_no_source"
        else:
            route = {"real_error": "b2_remediator_queue",
                     "false_alarm": "rule_scoping_queue"}.get(verdict, "human")
        routing.append({"review_id": rid, "rule_name": rule, "verdict": verdict,
                        "ambiguity_basis": obj.get("ambiguity_basis", ""),
                        "auto": is_auto, "route": route})

    out = batch_dir / "routing.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["review_id", "rule_name", "verdict",
                                          "ambiguity_basis", "auto", "route"])
        w.writeheader()
        w.writerows(routing)

    # Per-rule provisional (agent-relative) false-alarm precision among decided verdicts.
    rule_table = []
    for rule in sorted(by_rule):
        c = by_rule[rule]
        real, false = c.get("real_error", 0), c.get("false_alarm", 0)
        decided = real + false
        p, lo, hi = verdict_leaf.wilson(false, decided)
        rule_table.append({
            "rule_name": rule, "n": c["_n"], "real_error": real, "false_alarm": false,
            "ambiguous": c.get("ambiguous", 0), "no_source": c.get("no_source", 0),
            "n_decided": decided,
            "false_alarm_rate": None if decided == 0 else round(p, 4),
            "false_alarm_lo": None if decided == 0 else round(lo, 4),
            "false_alarm_hi": None if decided == 0 else round(hi, 4),
        })

    if release_locks:
        for rid in dispatched_ids:
            review_lock.release(rid)

    parity = None
    if compare_baseline is not None:
        parity = _compare_baseline(verdicts_dir, Path(compare_baseline), expected)
        with open(batch_dir / "parity.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["review_id", "fleet", "baseline", "match"])
            w.writeheader()
            w.writerows(parity["rows"])

    result = {
        "batch_id": batch_id,
        "schema_ok": summary["ok"],
        "n_verdicts": summary["n_files"],
        "n_schema_errors": summary["n_error_files"],
        "cross_errors": summary["cross_errors"],
        "n_dispatched": len(dispatched_ids),
        "n_auto": len(auto_ids),
        "per_rule": rule_table,
        "routing_csv": str(out),
        "parity": None if parity is None else {k: parity[k] for k in ("n_compared", "n_agree", "agreement")},
    }
    (batch_dir / "finalize_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _ids_from_csv(path: Path) -> set[str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["review_id"].strip() for r in csv.DictReader(f) if r.get("review_id")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Agent B1 driver (discover/finalize).")
    sub = parser.add_subparsers(dest="mode", required=True)

    d = sub.add_parser("discover")
    d.add_argument("batch_id")
    d.add_argument("--lane", choices=["blocker", "review"], default=None)
    d.add_argument("--engine", action="append", default=None)
    d.add_argument("--limit", type=int, default=None)
    d.add_argument("--review-id", action="append", default=None,
                   help="Select exactly this review_id (repeatable).")
    d.add_argument("--review-ids-from", type=Path, default=None,
                   help="Select exactly the review_ids in this CSV's review_id column "
                        "(e.g. a trial sample_manifest.csv).")

    f = sub.add_parser("finalize")
    f.add_argument("batch_id")
    f.add_argument("--no-release", action="store_true")
    f.add_argument("--compare-baseline", type=Path, default=None,
                   help="Verdicts dir to compare against (e.g. the in-session trial verdicts).")

    args = parser.parse_args(argv)
    if args.mode == "discover":
        ids: set[str] = set(args.review_id or [])
        if args.review_ids_from:
            ids |= _ids_from_csv(args.review_ids_from)
        res = discover(args.batch_id, lane=args.lane,
                       engines=set(args.engine) if args.engine else None,
                       review_ids=ids or None, limit=args.limit)
    else:
        res = finalize(args.batch_id, release_locks=not args.no_release,
                       compare_baseline=args.compare_baseline)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
