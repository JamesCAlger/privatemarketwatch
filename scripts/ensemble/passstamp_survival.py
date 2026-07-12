"""Verdict-survival join: carry pre-Wave-1 B1 labels onto the post-rebuild pool.

Era-windowing (docs/weak_rule_remediation_architecture.md section 5): B1 verdicts
describe the firing pool as of the pass they were drawn in. After a promotion wave
rebuilds unified holdings, each old decided verdict is reusable ONLY if the exact
same flag group still fires with the exact same composition. This script joins the
decided ens1/ens2 verdicts against the rebuilt review queue by review_id (a
deterministic hash of engine|rule|unit|period|mechanism) and classifies each:

  survived_exact   : review_id in new queue, n_units and metric unchanged
                     -> pass-stamped, credited toward recalibration quotas.
  survived_changed : review_id present but n_units/metric moved -> the group's
                     composition changed; the old group verdict no longer applies.
  dead_flag_gone   : review_id absent from the new queue (flag erased by fixes
                     or by rule demotion).
  excluded_recalibrated : the rule's own predicate/scope changed since the verdict
                     (334eb92 scope fixes + 2026-07-05 one-shot calibration), so
                     old labels describe the pre-fix pool regardless of survival.

Outputs (under --out-dir):
  passstamp_carryover.csv  -- one row per decided verdict with classification,
                              old/new group stats, fingerprint (rule|cik),
                              wave1_cik flag, and era stamp.
  passstamp_summary.md     -- per-rule credit table + classification rollup.

Purely additive; does NOT modify B1, the queue, or the verdict store. Read-only
outside --out-dir. No network. ASCII-only logging. Deterministic.

Usage:
    python -m scripts.ensemble.passstamp_survival \
        --old-queue data/output/ensemble/recal1/review_queue_pre_wave1_2026-06-28.csv \
        --out-dir data/output/ensemble/recal1
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import defaultdict
from pathlib import Path

from pipeline import config

logger = logging.getLogger(__name__)

DEFAULT_QUEUE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
DEFAULT_ENSEMBLE = config.OUTPUT_DIR / "ensemble"
DEFAULT_BATCHES = ("ens1", "ens2")
WAVE1_STORE = config.OVERRIDES_DIR / "agent_investigate_rules"

# Rules whose predicate or scope changed AFTER the ens1/ens2 verdicts were drawn
# (commit 334eb92 deterministic scope fixes + the 2026-07-05 one-shot calibration).
# Old labels on these rules describe the pre-fix firing pool by construction and
# must not seed post-fix priors, whether or not the flag survives.
DEFAULT_EXCLUDED_RULES = (
    "FX02", "FX03",          # USD unit-alias guard
    "X01",                   # preferred-equity exclusion
    "X07",                   # PRIVATE_EQUITY exclusion
    "C103",                  # sign-consistent unfunded-mark exclusion
    "C104", "C404",          # demoted to INFO/TRACK_ONLY
    "PCT01",                 # bound 200 -> 225
    "fmt_cost",              # weak-engine min -3e9
    "fmt_pct_of_net_assets",  # weak-engine min -100
    "pct_position_concentration",  # gate >= 0 added
)

DECIDED = {"real_error", "false_alarm"}

ERA_STAMP = "pre_wave1"  # the pass these verdicts were drawn in

CARRYOVER_COLUMNS = [
    "review_id", "batch", "engine", "rule_name", "cik", "report_date",
    "fingerprint", "verdict", "classification", "pass_stamped",
    "old_n_units", "new_n_units", "old_metric", "new_metric",
    "wave1_cik", "era", "stratum",
]


def _load_verdict_state(path: Path) -> str | None:
    """Return real_error/false_alarm for a decided leaf, else None."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            v = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    verdict = (v.get("verdict") or "").strip().lower()
    return verdict if verdict in DECIDED else None


def _load_queue(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            out[row["review_id"]] = row
    return out


def _load_batch_rids(base: Path, batches: list[str]) -> dict[str, dict[str, str]]:
    """review_id -> {batch, engine, rule_name, cik, report_date, stratum}; first batch wins."""
    rids: dict[str, dict[str, str]] = {}
    for batch in batches:
        f = base / batch / "review_ids.csv"
        if not f.exists():
            logger.warning("batch %s has no review_ids.csv -- skipped", batch)
            continue
        with open(f, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                rid = row["review_id"]
                if rid not in rids:
                    rids[rid] = {
                        "batch": batch,
                        "engine": row.get("engine", ""),
                        "rule_name": row.get("rule_name", ""),
                        "cik": row.get("cik", ""),
                        "report_date": row.get("report_date", ""),
                        "stratum": row.get("stratum", ""),
                    }
    return rids


def _wave1_ciks() -> set[str]:
    if not WAVE1_STORE.is_dir():
        return set()
    return {d.name.zfill(10) for d in WAVE1_STORE.iterdir() if d.is_dir()}


def _metric_eq(a: str, b: str) -> bool:
    if (a or "") == (b or ""):
        return True
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if fa == fb:
        return True
    scale = max(abs(fa), abs(fb))
    return scale > 0 and abs(fa - fb) / scale < 1e-9


def run(*, old_queue: Path, new_queue: Path, verdicts_dir: Path,
        ensemble_dir: Path, batches: list[str], excluded_rules: set[str],
        out_dir: Path) -> dict:
    old_q = _load_queue(old_queue)
    new_q = _load_queue(new_queue)
    rids = _load_batch_rids(ensemble_dir, batches)
    wave1 = _wave1_ciks()
    logger.info("old queue %d rows, new queue %d rows, %d sampled review_ids, %d wave-1 CIKs",
                len(old_q), len(new_q), len(rids), len(wave1))

    rows: list[dict[str, str]] = []
    per_rule: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    n_undecided = 0
    for rid, meta in sorted(rids.items()):
        state = _load_verdict_state(verdicts_dir / f"{rid}.json")
        if state is None:
            n_undecided += 1
            continue
        rule = meta["rule_name"]
        old_row = old_q.get(rid, {})
        new_row = new_q.get(rid)
        if rule in excluded_rules:
            cls = "excluded_recalibrated"
        elif new_row is None:
            cls = "dead_flag_gone"
        elif (old_row.get("n_units", "") == new_row.get("n_units", "")
                and _metric_eq(old_row.get("metric", ""), new_row.get("metric", ""))):
            cls = "survived_exact"
        else:
            cls = "survived_changed"
        stamped = cls == "survived_exact"
        cik10 = meta["cik"].zfill(10) if meta["cik"] else ""
        per_rule[rule][cls] += 1
        if stamped:
            per_rule[rule][f"credit_{state}"] += 1
        rows.append({
            "review_id": rid,
            "batch": meta["batch"],
            "engine": meta["engine"],
            "rule_name": rule,
            "cik": cik10,
            "report_date": meta["report_date"],
            "fingerprint": f"{rule}|{cik10}",
            "verdict": state,
            "classification": cls,
            "pass_stamped": str(stamped).lower(),
            "old_n_units": old_row.get("n_units", ""),
            "new_n_units": (new_row or {}).get("n_units", ""),
            "old_metric": old_row.get("metric", ""),
            "new_metric": (new_row or {}).get("metric", ""),
            "wave1_cik": str(cik10 in wave1).lower(),
            "era": ERA_STAMP,
            "stratum": meta["stratum"],
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "passstamp_carryover.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CARRYOVER_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    totals: dict[str, int] = defaultdict(int)
    for r in rows:
        totals[r["classification"]] += 1
    lines = [
        "# Pass-stamp survival: pre-Wave-1 verdicts vs post-rebuild pool", "",
        f"- old queue: `{old_queue.name}` ({len(old_q)} rows)",
        f"- new queue: `{new_queue}` ({len(new_q)} rows)",
        f"- decided verdicts joined: {len(rows)} (undecided/missing skipped: {n_undecided})",
        "",
        "| classification | n |", "|---|---|",
    ]
    for cls in ("survived_exact", "survived_changed", "dead_flag_gone", "excluded_recalibrated"):
        lines.append(f"| {cls} | {totals.get(cls, 0)} |")
    lines += ["", "## Per-rule carry-over credit (survived_exact only)", "",
              "| rule | credit_real | credit_fa | survived_changed | dead | excluded |",
              "|---|---|---|---|---|---|"]
    for rule in sorted(per_rule, key=lambda r: -(per_rule[r].get("credit_real_error", 0)
                                                 + per_rule[r].get("credit_false_alarm", 0))):
        c = per_rule[rule]
        lines.append(
            f"| {rule} | {c.get('credit_real_error', 0)} | {c.get('credit_false_alarm', 0)} "
            f"| {c.get('survived_changed', 0)} | {c.get('dead_flag_gone', 0)} "
            f"| {c.get('excluded_recalibrated', 0)} |")
    (out_dir / "passstamp_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("wrote %s (%d rows) and passstamp_summary.md", out_csv, len(rows))
    for cls, n in sorted(totals.items()):
        logger.info("  %-22s : %4d", cls, n)
    return {"rows": rows, "totals": dict(totals)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--old-queue", type=Path, required=True,
                        help="Pre-rebuild review_queue.csv snapshot (n_units/metric baseline).")
    parser.add_argument("--new-queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--verdicts-dir", type=Path, default=DEFAULT_VERDICTS)
    parser.add_argument("--ensemble-dir", type=Path, default=DEFAULT_ENSEMBLE)
    parser.add_argument("--batches", default=",".join(DEFAULT_BATCHES),
                        help="Comma-separated parent batch dirs holding review_ids.csv.")
    parser.add_argument("--excluded-rules", default=",".join(DEFAULT_EXCLUDED_RULES),
                        help="Rules recalibrated since the verdicts were drawn.")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(old_queue=args.old_queue, new_queue=args.new_queue,
        verdicts_dir=args.verdicts_dir, ensemble_dir=args.ensemble_dir,
        batches=[b.strip() for b in args.batches.split(",") if b.strip()],
        excluded_rules={r.strip() for r in args.excluded_rules.split(",") if r.strip()},
        out_dir=args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
