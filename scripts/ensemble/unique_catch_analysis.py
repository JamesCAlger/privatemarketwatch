"""Unique-catch analysis: do high-FP rules catch real errors no other rule catches?

Before killing/demoting a high-FP rule (X08, C107, C103, X10, PP01, ...) we need
to know whether its REAL-adjudicated flags are redundantly covered. Two coverage
notions, from weak to strong, per real flag at unit (cik, report_date):

  queue_covered   -- some OTHER rule also flags the same unit in the era-matched
                     review queue (the unit still enters review if this rule dies)
  kept_covered    -- some other rule OUTSIDE the high-FP set flags the unit
                     (coverage survives even if ALL high-FP rules die together)
  real_covered    -- some other rule's flag on the same unit was ALSO adjudicated
                     real_error (strongest: the defect signal is independently
                     confirmed, though possibly a different defect on the unit)

A real flag with kept_covered=False is a UNIQUE CATCH: killing the rule (plus
the rest of the high-FP set) silently drops that unit from review.

Caveat (inherits B1 semantics): B1 adjudicates flag GROUPS per (rule, unit);
"real" can mean 1 real row of many. Co-firing rules on a unit may point at
DIFFERENT defects, so real_covered overstates true defect-level redundancy;
queue/kept coverage only claims the unit still gets reviewed. Mechanisms of the
unique catches are reported so defect families can be eyeballed.

Inputs:
  data/output/ensemble/{ens1,ens2,recal1}/review_ids.csv     -- adjudication frames
  data/output/ensemble/recal1/passstamp_carryover.csv        -- prior decided verdicts
                                                                (survived_exact only)
  data/output/review_queue/verdicts/<rid>.json               -- B1 verdict leaves
  data/output/ensemble/recal1/review_queue_pre_wave1_2026-06-28.csv -- pre-wave1 queue
  data/output/review_queue/review_queue.csv                  -- current (post-wave1) queue

Outputs (data/output/ensemble/unique_catch/):
  unique_catch_per_rule.csv  -- per-rule coverage summary over its real flags
  unique_catch_detail.csv    -- one row per real flag of a high-FP rule
  unique_catch_summary.md

Read-only on verdicts and queues. ASCII-only logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import defaultdict
from pathlib import Path

from pipeline import config
from scripts.ensemble.analyze_ensemble import _load_verdict, _verdict_state

logger = logging.getLogger(__name__)

OUT_BASE = config.OUTPUT_DIR / "ensemble"
VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
OUT_DIR = OUT_BASE / "unique_catch"

# High-FP set under kill/demote consideration (ens2 + recal1 combined evidence).
# C104/C404 are already demoted to INFO; included so "kept" coverage excludes them.
HIGH_FP_RULES = {
    "X08", "C103", "C104", "C404", "C107", "X10", "PP01",
    "X01", "X07", "fmt_pct_of_net_assets", "fmt_basis_spread",
}

FRAMES = ("ens1", "ens2", "recal1")
PRE_WAVE1_QUEUE = OUT_BASE / "recal1" / "review_queue_pre_wave1_2026-06-28.csv"
CURRENT_QUEUE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _load_decided_flags(verdicts_dir: Path) -> list[dict]:
    """All decided (real/FA) flag-level verdicts with rule + unit + era."""
    flags: dict[str, dict] = {}
    for batch in FRAMES:
        frame = OUT_BASE / batch / "review_ids.csv"
        if not frame.exists():
            continue
        era = "post_wave1" if batch.startswith("recal") else "pre_wave1"
        for r in _read_csv(frame):
            rid = r["review_id"]
            if rid in flags:
                continue
            v = _load_verdict(verdicts_dir / f"{rid}.json")
            if v is None:
                continue
            state = _verdict_state(v)
            if state not in ("real_error", "false_alarm"):
                continue
            flags[rid] = {
                "review_id": rid, "batch": batch, "era": era,
                "engine": r.get("engine", ""), "rule_name": r["rule_name"],
                "cik": r["cik"], "report_date": r["report_date"],
                "verdict": state, "mechanism": v.get("mechanism", ""),
            }
    # Pass-stamped carry-over: prior decided verdicts whose flags survived the
    # Wave-1 rebuild exactly -- valid labels for the post-wave1 era too, but we
    # credit them in their original (pre_wave1) era for queue matching.
    carry = OUT_BASE / "recal1" / "passstamp_carryover.csv"
    if carry.exists():
        for r in _read_csv(carry):
            rid = r["review_id"]
            if rid in flags or r.get("classification") != "survived_exact":
                continue
            verdict = (r.get("verdict") or "").strip().lower()
            if verdict not in ("real_error", "false_alarm"):
                continue
            flags[rid] = {
                "review_id": rid, "batch": r.get("batch", "carry"),
                "era": "pre_wave1", "engine": r.get("engine", ""),
                "rule_name": r["rule_name"], "cik": r["cik"],
                "report_date": r["report_date"], "verdict": verdict,
                "mechanism": "",
            }
    return list(flags.values())


def _load_queue_units(path: Path) -> dict[tuple[str, str], set[tuple[str, str]]]:
    """unit (cik, report_date) -> set of (engine, rule_name) flagging it."""
    units: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for r in _read_csv(path):
        cik, rd = (r.get("cik") or "").strip(), (r.get("report_date") or "").strip()
        if not cik or not rd:
            continue
        units[(cik, rd)].add((r.get("engine", ""), r.get("rule_name", "")))
    return units


def analyze(verdicts_dir: Path = VERDICTS, out_dir: Path = OUT_DIR) -> dict:
    flags = _load_decided_flags(verdicts_dir)
    logger.info("decided flag-level verdicts loaded: %d", len(flags))

    queues = {
        "pre_wave1": _load_queue_units(PRE_WAVE1_QUEUE),
        "post_wave1": _load_queue_units(CURRENT_QUEUE),
    }
    for era, q in queues.items():
        logger.info("queue[%s]: %d units", era, len(q))

    # Adjudicated-real units by (unit) -> set of rules with a real verdict there.
    real_rules_by_unit: dict[tuple[str, str], set[str]] = defaultdict(set)
    for f in flags:
        if f["verdict"] == "real_error":
            real_rules_by_unit[(f["cik"], f["report_date"])].add(f["rule_name"])

    per_rule_rows, detail_rows = [], []
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for f in flags:
        by_rule[f["rule_name"]].append(f)

    for rule in sorted(by_rule):
        fs = by_rule[rule]
        n = len(fs)
        reals = [f for f in fs if f["verdict"] == "real_error"]
        fp_rate = (n - len(reals)) / n if n else float("nan")
        q_cov = k_cov = r_cov = 0
        unique_units, unique_mechs = [], []
        for f in reals:
            unit = (f["cik"], f["report_date"])
            # era-matched queue first; fall back to the other era (ens1 units
            # can predate the pre-wave1 snapshot's draw)
            cofire = set()
            for era in (f["era"], "post_wave1" if f["era"] == "pre_wave1" else "pre_wave1"):
                if unit in queues[era]:
                    cofire = {rn for (_e, rn) in queues[era][unit]}
                    break
            others = cofire - {rule}
            others_kept = others - HIGH_FP_RULES
            others_real = real_rules_by_unit.get(unit, set()) - {rule}
            queue_covered = bool(others)
            kept_covered = bool(others_kept)
            real_covered = bool(others_real)
            q_cov += queue_covered
            k_cov += kept_covered
            r_cov += real_covered
            if not kept_covered:
                unique_units.append(f"{f['cik']}@{f['report_date']}")
                unique_mechs.append(f["mechanism"] or "?")
            if rule in HIGH_FP_RULES:
                detail_rows.append({
                    "rule_name": rule, "review_id": f["review_id"],
                    "batch": f["batch"], "cik": f["cik"],
                    "report_date": f["report_date"], "mechanism": f["mechanism"],
                    "queue_covered": queue_covered, "kept_covered": kept_covered,
                    "real_covered": real_covered,
                    "cofiring_kept_rules": ";".join(sorted(others_kept)),
                    "other_real_rules": ";".join(sorted(others_real)),
                })
        nr = len(reals)
        per_rule_rows.append({
            "rule_name": rule, "high_fp_set": rule in HIGH_FP_RULES,
            "n_decided": n, "n_real": nr, "fp_rate": f"{fp_rate:.3f}",
            "real_queue_covered": q_cov, "real_kept_covered": k_cov,
            "real_other_real_covered": r_cov,
            "unique_catches": nr - k_cov,
            "unique_units": ";".join(unique_units),
            "unique_mechanisms": ";".join(unique_mechs),
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "unique_catch_per_rule.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_rule_rows[0]))
        w.writeheader()
        w.writerows(per_rule_rows)
    with open(out_dir / "unique_catch_detail.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(detail_rows[0]))
        w.writeheader()
        w.writerows(detail_rows)

    hi = [r for r in per_rule_rows if r["high_fp_set"]]
    lines = [
        "# Unique-catch analysis: high-FP rules",
        "",
        f"- decided flag-level verdicts: {len(flags)} "
        f"(frames {', '.join(FRAMES)} + survived_exact carryover)",
        "- unit = (cik, report_date); coverage = another rule flags the same unit",
        "- kept_covered excludes the whole high-FP set: "
        + ", ".join(sorted(HIGH_FP_RULES)),
        "",
        "| rule | n_real | FP rate | queue-cov | kept-cov | other-real-cov | UNIQUE |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in hi:
        lines.append(
            f"| {r['rule_name']} | {r['n_real']} | {r['fp_rate']} | "
            f"{r['real_queue_covered']} | {r['real_kept_covered']} | "
            f"{r['real_other_real_covered']} | {r['unique_catches']} |")
    lines += ["", "Unique catches (unit, mechanism):", ""]
    for r in hi:
        if int(r["unique_catches"]):
            lines.append(f"- {r['rule_name']}: {r['unique_units']} "
                         f"[{r['unique_mechanisms']}]")
    (out_dir / "unique_catch_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    logger.info("wrote %s", out_dir)
    return {"flags": len(flags), "rules": len(per_rule_rows),
            "high_fp_unique": {r["rule_name"]: int(r["unique_catches"]) for r in hi}}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verdicts-dir", type=Path, default=VERDICTS)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = p.parse_args()
    res = analyze(verdicts_dir=args.verdicts_dir, out_dir=args.out_dir)
    logger.info("unique catches by high-FP rule: %s", res["high_fp_unique"])


if __name__ == "__main__":
    main()
