"""Unit-stratified sampler for the weak-rule false-positive + ensemble B1 experiment.

Goal: from the unified review queue, draw a statistically deliberate sample of
fund-quarter UNITS (cik, report_date), stratified by co-firing degree (how many
distinct in-scope weak rules fire on the unit), and emit exactly the review_ids
to adjudicate. Adjudicating every in-scope weak flag on each sampled unit yields
BOTH:

  (i)  pooled per-rule false-positive (false_alarm) rates, and
  (ii) the co-firing -> precision relationship needed to test whether an ensemble
       of weak rules is a better defect indicator than any single rule.

This script is PURELY ADDITIVE. It does NOT modify Agent B1. It writes a
review_ids.csv that the UNMODIFIED B1 driver consumes via:

    python -m scripts.agent_b.run_review discover <batch_id> \
        --review-ids-from data/output/ensemble/<batch_id>/review_ids.csv

In-scope rules = review-lane (weak) rules with >= --min-firings firings in the
queue. The co-firing manifest records the FULL set of weak rules that fired on
each sampled unit (in-scope and out-of-scope) so the ensemble feature vector is
complete even though we only spend adjudication budget on in-scope rules.

No network. Read-only on the queue; writes only under data/output/ensemble/.
ASCII-only logging (Windows cp1252 safe). Deterministic given --seed.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
from collections import defaultdict
from pathlib import Path

from pipeline import config

logger = logging.getLogger(__name__)

DEFAULT_QUEUE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"
DEFAULT_OUT_BASE = config.OUTPUT_DIR / "ensemble"

# Co-firing-degree strata. degree = number of DISTINCT in-scope weak rules on a unit.
# Edges are inclusive lower bounds; the last stratum is open-ended.
STRATA = [
    ("d1", 1, 1),
    ("d2_3", 2, 3),
    ("d4_7", 4, 7),
    ("d8plus", 8, 10**9),
]

# Default UNIT allocation per stratum (tuned via --profile to land near --target
# total adjudications under the Standard ~1,000 budget). Override on the CLI.
DEFAULT_ALLOC = {"d1": 55, "d2_3": 55, "d4_7": 45, "d8plus": 35}

# Default UNIT allocation for a pilot subset (~150 adjudications), drawn as a STRICT
# subset of an existing batch's selected units so no adjudication is ever wasted.
DEFAULT_PILOT_ALLOC = {"d1": 30, "d2_3": 20, "d4_7": 8, "d8plus": 3}


def _stratum(degree: int) -> str:
    for name, lo, hi in STRATA:
        if lo <= degree <= hi:
            return name
    return STRATA[-1][0]


def _load_units(queue_path: Path, min_firings: int) -> tuple[dict, set[str]]:
    """Return (units, in_scope_rules).

    units: keyed by (cik, report_date) for localizable review-lane rows. Each value:
      {
        "flags":    [ {review_id, engine, rule_name} ... ]  # in-scope flags only
        "in_scope_rules": set[str]                            # distinct in-scope rules
        "all_weak_rules": set[str]                            # every weak rule fired (feature)
      }
    in_scope_rules: review-lane rule_names with >= min_firings firings.
    """
    rows = []
    rule_counts: dict[str, int] = defaultdict(int)
    with open(queue_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if (r.get("lane") or "").strip().lower() != "review":
                continue
            rows.append(r)
            rule_counts[r.get("rule_name", "").strip()] += 1

    in_scope = {rn for rn, c in rule_counts.items() if c >= min_firings and rn}

    units: dict[tuple[str, str], dict] = {}
    for r in rows:
        cik = (r.get("cik") or "").strip()
        rdate = (r.get("report_date") or "").strip()
        if not cik or not rdate:
            continue  # ensemble frame is localizable fund-quarter units only
        rule = (r.get("rule_name") or "").strip()
        key = (cik, rdate)
        u = units.setdefault(
            key, {"flags": [], "in_scope_rules": set(), "all_weak_rules": set()}
        )
        u["all_weak_rules"].add(rule)
        if rule in in_scope:
            u["flags"].append(
                {
                    "review_id": (r.get("review_id") or "").strip(),
                    "engine": (r.get("engine") or "").strip(),
                    "rule_name": rule,
                }
            )
            u["in_scope_rules"].add(rule)
    # Drop units with no in-scope flag (degree 0) -- nothing to adjudicate there.
    units = {k: v for k, v in units.items() if v["in_scope_rules"]}
    return units, in_scope


def _profile(units: dict) -> dict:
    by_stratum: dict[str, list] = defaultdict(list)
    for key, u in units.items():
        deg = len(u["in_scope_rules"])
        by_stratum[_stratum(deg)].append((key, len(u["flags"])))
    prof = {}
    for name, _, _ in STRATA:
        items = by_stratum.get(name, [])
        n_units = len(items)
        mean_flags = (sum(f for _, f in items) / n_units) if n_units else 0.0
        prof[name] = {"n_units": n_units, "mean_flags_per_unit": round(mean_flags, 2)}
    return prof


def build(
    *,
    queue_path: Path,
    out_dir: Path,
    min_firings: int,
    alloc: dict[str, int],
    seed: int,
) -> dict:
    units, in_scope = _load_units(queue_path, min_firings)
    rng = random.Random(seed)

    # Group unit keys by stratum, deterministically ordered then sampled.
    by_stratum: dict[str, list] = defaultdict(list)
    for key, u in units.items():
        by_stratum[_stratum(len(u["in_scope_rules"]))].append(key)

    selected_keys: list[tuple[str, str]] = []
    alloc_report = {}
    for name, _, _ in STRATA:
        pool = sorted(by_stratum.get(name, []))  # deterministic order
        want = alloc.get(name, 0)
        take = min(want, len(pool))
        chosen = rng.sample(pool, take) if take else []
        selected_keys.extend(chosen)
        alloc_report[name] = {"requested": want, "available": len(pool), "selected": take}

    # Emit review_ids.csv (every in-scope flag on each selected unit) + manifest.
    out_dir.mkdir(parents=True, exist_ok=True)
    review_ids_path = out_dir / "review_ids.csv"
    manifest_path = out_dir / "cofire_manifest.json"

    manifest_units = []
    n_adjudications = 0
    seen_rids: set[str] = set()
    with open(review_ids_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["review_id", "cik", "report_date", "engine", "rule_name", "stratum"])
        for key in selected_keys:
            cik, rdate = key
            u = units[key]
            deg = len(u["in_scope_rules"])
            stratum = _stratum(deg)
            for fl in u["flags"]:
                rid = fl["review_id"]
                if rid in seen_rids:
                    continue  # de-dup: a review_id is adjudicated once even if shared
                seen_rids.add(rid)
                w.writerow([rid, cik, rdate, fl["engine"], fl["rule_name"], stratum])
                n_adjudications += 1
            manifest_units.append(
                {
                    "cik": cik,
                    "report_date": rdate,
                    "stratum": stratum,
                    "degree": deg,
                    "in_scope_rules": sorted(u["in_scope_rules"]),
                    "all_weak_rules": sorted(u["all_weak_rules"]),
                    "review_ids": [fl["review_id"] for fl in u["flags"]],
                }
            )

    manifest = {
        "seed": seed,
        "min_firings": min_firings,
        "in_scope_rule_count": len(in_scope),
        "in_scope_rules": sorted(in_scope),
        "n_units_selected": len(selected_keys),
        "n_adjudications": n_adjudications,
        "allocation": alloc_report,
        "units": manifest_units,
    }
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    return {
        "review_ids_path": str(review_ids_path),
        "manifest_path": str(manifest_path),
        "n_units": len(selected_keys),
        "n_adjudications": n_adjudications,
        "in_scope_rules": len(in_scope),
        "allocation": alloc_report,
    }


def _read_batch(src_dir: Path) -> tuple[dict, dict]:
    """Return (rows_by_unit, manifest) for an existing ensemble batch dir."""
    manifest = json.loads((src_dir / "cofire_manifest.json").read_text(encoding="utf-8"))
    rows_by_unit: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with open(src_dir / "review_ids.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows_by_unit[(r["cik"], r["report_date"])].append(r)
    return rows_by_unit, manifest


def _emit_subset(out_dir: Path, keys: set[tuple[str, str]], rows_by_unit: dict, src_manifest: dict) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    n_adj = 0
    with open(out_dir / "review_ids.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["review_id", "cik", "report_date", "engine", "rule_name", "stratum"])
        for key in sorted(keys):
            for r in rows_by_unit[key]:
                w.writerow([r["review_id"], r["cik"], r["report_date"], r["engine"], r["rule_name"], r["stratum"]])
                n_adj += 1
    units = [u for u in src_manifest["units"] if (u["cik"], u["report_date"]) in keys]
    manifest = dict(src_manifest)
    manifest["units"] = units
    manifest["n_units_selected"] = len(units)
    manifest["n_adjudications"] = n_adj
    manifest["derived_from"] = src_manifest.get("seed")
    (out_dir / "cofire_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"n_units": len(units), "n_adjudications": n_adj}


def build_pilot_split(*, src_batch: str, pilot_batch: str, rest_batch: str, alloc: dict, seed: int) -> dict:
    """Split an existing batch's selected units into a pilot subset + the remainder.

    Pilot units are a STRICT subset of src; rest = src - pilot. The two are disjoint,
    so they can be discovered/preflighted/dispatched as independent B1 batches with no
    lock or verdict collisions, and together reconstitute the full src sample.
    """
    src_dir = DEFAULT_OUT_BASE / src_batch
    rows_by_unit, manifest = _read_batch(src_dir)
    rng = random.Random(seed)

    by_stratum: dict[str, list] = defaultdict(list)
    for u in manifest["units"]:
        by_stratum[u["stratum"]].append((u["cik"], u["report_date"]))

    pilot_keys: set[tuple[str, str]] = set()
    split_report = {}
    for name, _, _ in STRATA:
        pool = sorted(by_stratum.get(name, []))
        take = min(alloc.get(name, 0), len(pool))
        chosen = rng.sample(pool, take) if take else []
        pilot_keys.update(chosen)
        split_report[name] = {"src_units": len(pool), "pilot_units": take}
    all_keys = {(u["cik"], u["report_date"]) for u in manifest["units"]}
    rest_keys = all_keys - pilot_keys

    pilot = _emit_subset(DEFAULT_OUT_BASE / pilot_batch, pilot_keys, rows_by_unit, manifest)
    rest = _emit_subset(DEFAULT_OUT_BASE / rest_batch, rest_keys, rows_by_unit, manifest)
    return {"split": split_report, "pilot": pilot, "rest": rest,
            "pilot_dir": str(DEFAULT_OUT_BASE / pilot_batch), "rest_dir": str(DEFAULT_OUT_BASE / rest_batch)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Unit-stratified sampler for the weak-rule FP + ensemble B1 experiment.")
    p.add_argument("--pilot-of", default=None, metavar="SRC_BATCH",
                   help="Split SRC_BATCH's selected units into a disjoint pilot subset + remainder, then exit.")
    p.add_argument("--pilot-batch-id", default=None, help="Pilot output batch id (default: <src>_pilot).")
    p.add_argument("--rest-batch-id", default=None, help="Remainder output batch id (default: <src>_rest).")
    for name, _, _ in STRATA:
        p.add_argument(f"--pilot-n-{name}", type=int, default=DEFAULT_PILOT_ALLOC[name], help=f"Pilot units from stratum {name}.")
    p.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    p.add_argument("--batch-id", default="ens1", help="Output dir = data/output/ensemble/<batch_id>/")
    p.add_argument("--min-firings", type=int, default=30, help="In-scope = weak rules with >= this many firings.")
    p.add_argument("--seed", type=int, default=20260628)
    p.add_argument("--target", type=int, default=1000, help="Informational target adjudication count (Standard budget).")
    for name, _, _ in STRATA:
        p.add_argument(f"--n-{name}", type=int, default=DEFAULT_ALLOC[name], help=f"Units to sample from stratum {name}.")
    p.add_argument("--profile", action="store_true", help="Print the stratum population and exit (no writes).")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.pilot_of:
        pilot_batch = args.pilot_batch_id or f"{args.pilot_of}_pilot"
        rest_batch = args.rest_batch_id or f"{args.pilot_of}_rest"
        alloc = {name: getattr(args, f"pilot_n_{name}") for name, _, _ in STRATA}
        res = build_pilot_split(src_batch=args.pilot_of, pilot_batch=pilot_batch,
                                rest_batch=rest_batch, alloc=alloc, seed=args.seed)
        logger.info("pilot split of '%s' (strict subset): %s", args.pilot_of, res["split"])
        logger.info("PILOT '%s': %d units, %d adjudications -> %s",
                    pilot_batch, res["pilot"]["n_units"], res["pilot"]["n_adjudications"], res["pilot_dir"])
        logger.info("REST  '%s': %d units, %d adjudications -> %s",
                    rest_batch, res["rest"]["n_units"], res["rest"]["n_adjudications"], res["rest_dir"])
        return 0

    units, in_scope = _load_units(args.queue, args.min_firings)
    prof = _profile(units)
    logger.info("in-scope weak rules (>=%d firings): %d", args.min_firings, len(in_scope))
    logger.info("localizable units with >=1 in-scope flag: %d", len(units))
    for name, _, _ in STRATA:
        s = prof[name]
        logger.info("  stratum %-7s: %5d units, mean %.2f in-scope flags/unit", name, s["n_units"], s["mean_flags_per_unit"])
    # Projected adjudications under the requested allocation.
    alloc = {name: getattr(args, f"n_{name}") for name, _, _ in STRATA}
    projected = sum(min(alloc[n], prof[n]["n_units"]) * prof[n]["mean_flags_per_unit"] for n, _, _ in STRATA)
    logger.info("requested allocation: %s -> projected ~%d adjudications (target %d)", alloc, round(projected), args.target)

    if args.profile:
        return 0

    out_dir = DEFAULT_OUT_BASE / args.batch_id
    res = build(queue_path=args.queue, out_dir=out_dir, min_firings=args.min_firings, alloc=alloc, seed=args.seed)
    logger.info("SELECTED %d units -> %d adjudications across %d in-scope rules", res["n_units"], res["n_adjudications"], res["in_scope_rules"])
    logger.info("wrote %s", res["review_ids_path"])
    logger.info("wrote %s", res["manifest_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
