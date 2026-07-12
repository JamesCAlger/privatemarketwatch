"""Draw the post-rebuild B1 recalibration batch (per-rule + per-group quotas).

Implements the batch specified in docs/weak_rule_remediation_architecture.md
section 5 step 2: ONE modest batch that double-duties as (i) fresh per-rule
priors on the post-promotion-wave firing pool and (ii) per-fingerprint-group
minimum quotas on the divergent candidate groups from the ens2 retrospective
re-cut. Pass-stamped carry-over labels (passstamp_survival.py) reduce the new
adjudication spend: a rule's quota is met first by surviving pre-wave labels,
and only the shortfall is drawn.

Frame rules (inherited from sample_units.py after the ens1 scope correction):
review lane only, wrapper-cohort CIKs only, no-accession engines excluded.
Additionally excludes any review_id that already has a verdict leaf (B1
preflight aborts on existing verdicts) and the recalibrated rules whose
predicates changed since ens2 (they need no carry-over accounting here because
their old labels are excluded upstream; they re-enter as ordinary rules with
zero credit).

Outputs (under --out-dir):
  review_ids.csv       -- the dispatch frame (ens2 schema + fingerprint,
                          quota_source, era columns).
  recal_manifest.json  -- parameters, credits, quotas, per-rule shortfalls.
  recal_shortfall.csv  -- per-rule accounting: pool, credit, target, drawn.

Purely additive; does NOT modify B1 or the queue. Read-only outside --out-dir.
No network. ASCII-only logging. Deterministic given --seed.

Usage (from repo root):
    python scripts/ensemble/draw_recal_batch.py \
        --carryover data/output/ensemble/recal1/passstamp_carryover.csv \
        --out-dir data/output/ensemble/recal1
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import config
from sample_units import DEFAULT_EXCLUDE_ENGINES, _load_cohort_ciks  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_QUEUE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
DEFAULT_GROUPS = config.OUTPUT_DIR / "ensemble" / "ens2" / "fingerprint_groups.csv"

ERA = "post_wave1_pass1"

FRAME_COLUMNS = ["review_id", "cik", "report_date", "engine", "rule_name",
                 "fingerprint", "quota_source", "era"]


def _load_divergent_groups(path: Path, min_n: int) -> list[tuple[str, str]]:
    """(rule, cik) groups the ens2 re-cut flags as routing-divergent."""
    out: list[tuple[str, str]] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("raw_disagree") == "1" and int(float(row["n"])) >= min_n:
                out.append((row["rule"], row["cik"].zfill(10)))
    return sorted(out)


def _load_review_pool(queue: Path, cohort: set[str], exclude_engines: set[str],
                      verdicts_dir: Path) -> list[dict[str, str]]:
    pool: list[dict[str, str]] = []
    n_lane = n_cohort = n_engine = n_verdict = 0
    with open(queue, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("lane") != "review":
                n_lane += 1
                continue
            if row.get("engine") in exclude_engines:
                n_engine += 1
                continue
            cik = (row.get("cik") or "").lstrip("0")
            if not cik or cik not in cohort:
                n_cohort += 1
                continue
            if (verdicts_dir / f"{row['review_id']}.json").exists():
                n_verdict += 1
                continue
            pool.append(row)
    logger.info("pool: %d flags (dropped %d non-review, %d non-cohort, %d excluded-engine, "
                "%d already-adjudicated)", len(pool), n_lane, n_cohort, n_engine, n_verdict)
    return pool


def _load_credits(carryover: Path) -> tuple[dict[str, int], dict[str, int]]:
    """survived_exact credit per rule and per fingerprint (rule|cik)."""
    rule_credit: dict[str, int] = defaultdict(int)
    group_credit: dict[str, int] = defaultdict(int)
    with open(carryover, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("pass_stamped") == "true":
                rule_credit[row["rule_name"]] += 1
                group_credit[row["fingerprint"]] += 1
    return rule_credit, group_credit


def draw(*, queue: Path, verdicts_dir: Path, carryover: Path, groups_file: Path,
         out_dir: Path, rule_target: int, group_target: int, min_firings: int,
         group_min_n: int, budget: int, seed: int) -> dict:
    cohort = _load_cohort_ciks(config.WRAPPER_COHORT_MANIFEST_FILE)
    pool = _load_review_pool(queue, cohort, set(DEFAULT_EXCLUDE_ENGINES), verdicts_dir)
    rule_credit, group_credit = _load_credits(carryover)
    divergent = _load_divergent_groups(groups_file, group_min_n)
    rng = random.Random(seed)

    by_rule: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_group: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pool:
        rule = row["rule_name"]
        by_rule[rule].append(row)
        by_group[f"{rule}|{(row.get('cik') or '').zfill(10)}"].append(row)

    in_scope = sorted(r for r, rows in by_rule.items() if len(rows) >= min_firings)
    logger.info("in-scope rules (>=%d firings in scoped pool): %d", min_firings, len(in_scope))

    selected: dict[str, dict[str, str]] = {}  # review_id -> row (+quota_source)

    def _take(rows: list[dict[str, str]], k: int, source: str) -> int:
        fresh = sorted((r for r in rows if r["review_id"] not in selected),
                       key=lambda r: r["review_id"])
        picked = rng.sample(fresh, min(k, len(fresh)))
        for r in picked:
            selected[r["review_id"]] = {**r, "quota_source": source}
        return len(picked)

    # 1) Divergent-group minimum quotas first (the spec's priority spend).
    group_quota_drawn: dict[str, int] = {}
    for rule, cik in divergent:
        fp = f"{rule}|{cik}"
        need = max(0, group_target - group_credit.get(fp, 0))
        got = _take(by_group.get(fp, []), need, f"group:{fp}")
        group_quota_drawn[fp] = got
        logger.info("group %-24s credit %2d, need %2d, drawn %2d (pool %d)",
                    fp, group_credit.get(fp, 0), need, got, len(by_group.get(fp, [])))

    # 2) Per-rule fresh-pool top-up to the recalibration target.
    for rule in in_scope:
        already = sum(1 for r in selected.values() if r["rule_name"] == rule)
        need = max(0, rule_target - rule_credit.get(rule, 0) - already)
        _take(by_rule[rule], need, f"rule:{rule}")

    # 3) Budget cap: group quotas are never cut; trim rule top-ups at random
    #    (seeded), spreading the cut across rules rather than dropping whole rules.
    n_group = sum(1 for r in selected.values() if r["quota_source"].startswith("group:"))
    over = len(selected) - budget
    if over > 0:
        rule_picks = sorted((rid for rid, r in selected.items()
                             if r["quota_source"].startswith("rule:")))
        rng.shuffle(rule_picks)
        for rid in rule_picks[:over]:
            del selected[rid]
        logger.info("budget cap %d: trimmed %d rule-quota draws", budget, over)

    # 4) Final per-rule accounting AFTER the cap, so the shortfall table matches
    #    the emitted frame exactly.
    rule_rows: list[dict[str, object]] = []
    for rule in in_scope:
        credit = rule_credit.get(rule, 0)
        grp = sum(1 for r in selected.values()
                  if r["rule_name"] == rule and r["quota_source"].startswith("group:"))
        drawn = sum(1 for r in selected.values()
                    if r["rule_name"] == rule and r["quota_source"].startswith("rule:"))
        rule_rows.append({"rule_name": rule, "pool": len(by_rule[rule]), "credit": credit,
                          "group_drawn": grp, "target": rule_target, "drawn": drawn,
                          "unmet": max(0, rule_target - credit - grp - drawn)})

    out_dir.mkdir(parents=True, exist_ok=True)
    frame = sorted(selected.values(), key=lambda r: r["review_id"])
    with open(out_dir / "review_ids.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FRAME_COLUMNS)
        w.writeheader()
        for r in frame:
            cik10 = (r.get("cik") or "").zfill(10)
            w.writerow({"review_id": r["review_id"], "cik": cik10,
                        "report_date": r.get("report_date", ""),
                        "engine": r.get("engine", ""), "rule_name": r["rule_name"],
                        "fingerprint": f"{r['rule_name']}|{cik10}",
                        "quota_source": r["quota_source"], "era": ERA})

    with open(out_dir / "recal_shortfall.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["rule_name", "pool", "credit", "group_drawn",
                                           "target", "drawn", "unmet"])
        w.writeheader()
        w.writerows(rule_rows)

    manifest = {
        "batch": out_dir.name,
        "era": ERA,
        "seed": seed,
        "queue": str(queue),
        "carryover": str(carryover),
        "rule_target": rule_target,
        "group_target": group_target,
        "min_firings": min_firings,
        "budget": budget,
        "cohort_scoped": True,
        "excluded_engines": sorted(DEFAULT_EXCLUDE_ENGINES),
        "divergent_groups": [f"{r}|{c}" for r, c in divergent],
        "group_quota_drawn": group_quota_drawn,
        "n_selected": len(frame),
        "n_group_quota": n_group,
        "n_rule_quota": len(frame) - n_group,
        "in_scope_rules": in_scope,
        "rule_credit": dict(rule_credit),
    }
    (out_dir / "recal_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("frame: %d review_ids (%d group-quota + %d rule-quota) -> %s",
                len(frame), n_group, len(frame) - n_group, out_dir / "review_ids.csv")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--verdicts-dir", type=Path, default=DEFAULT_VERDICTS)
    parser.add_argument("--carryover", type=Path, required=True)
    parser.add_argument("--groups-file", type=Path, default=DEFAULT_GROUPS)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--rule-target", type=int, default=30,
                        help="Decided labels wanted per in-scope rule (carry-over counts).")
    parser.add_argument("--group-target", type=int, default=25,
                        help="Minimum labels per divergent fingerprint group.")
    parser.add_argument("--min-firings", type=int, default=30,
                        help="Rule in-scope threshold on the scoped post-rebuild pool.")
    parser.add_argument("--group-min-n", type=int, default=4,
                        help="Min ens2 sample size for a divergent group to get a quota.")
    parser.add_argument("--budget", type=int, default=250,
                        help="Hard cap on new adjudications (group quotas never cut).")
    parser.add_argument("--seed", type=int, default=20260711)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    draw(queue=args.queue, verdicts_dir=args.verdicts_dir, carryover=args.carryover,
         groups_file=args.groups_file, out_dir=args.out_dir, rule_target=args.rule_target,
         group_target=args.group_target, min_firings=args.min_firings,
         group_min_n=args.group_min_n, budget=args.budget, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
