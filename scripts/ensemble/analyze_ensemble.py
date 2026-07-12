"""Ensemble + false-positive analysis for the weak-rule B1 experiment.

Consumes (a) the co-firing manifest written by scripts.ensemble.sample_units and
(b) the B1 verdict leaves (data/output/review_queue/verdicts/*.json) produced by
the UNMODIFIED Agent B1 fleet. Produces:

  per_rule_fp.csv      -- per-rule false-positive (false_alarm) rate with Wilson 95% CI.
  ensemble_by_degree.csv -- does the chance a flag is a real error rise with co-firing
                            degree? (flag-level real rate + unit-level "any real" rate by stratum)
  rule_lift.csv        -- per rule: real-error rate when it fires ALONE (unit degree 1)
                          vs when it co-fires (degree >= 2). The precision-lift signal.
  ensemble_summary.md  -- human-readable rollup.

Verdict accounting matches B1's finalize semantics:
  decided = real_error + false_alarm. ambiguous and auto/no-source verdicts are
  EXCLUDED from rates (they are coverage/infra states, not adjudications).

A `--coverage` mode reports per-rule sample sizes from review_ids.csv alone (before
any verdicts exist) so the batch can be sanity-checked pre-dispatch.

Read-only on verdicts; writes only under data/output/ensemble/<batch_id>/.
No network. ASCII-only logging. Reuses pipeline.verdict_leaf.wilson for CI parity.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

from pipeline import config
from pipeline.verdict_leaf import wilson

logger = logging.getLogger(__name__)

DEFAULT_OUT_BASE = config.OUTPUT_DIR / "ensemble"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"

DECIDED = {"real_error", "false_alarm"}


def _load_verdict(path: Path) -> dict | None:
    # utf-8-sig: tolerate a UTF-8 BOM, which Codex workers sometimes write and which
    # plain utf-8 json.load rejects. (B1 finalize uses strict utf-8; run
    # scripts/ensemble/strip_verdict_bom.py before finalize if BOMs appear.)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _verdict_state(v: dict) -> str:
    """Collapse a verdict leaf to one of: real_error, false_alarm, ambiguous, auto, no_source."""
    if v.get("auto") is True:
        return "auto"
    verdict = (v.get("verdict") or "").strip().lower()
    if verdict == "ambiguous":
        basis = (v.get("ambiguity_basis") or "").strip().lower()
        return "no_source" if basis == "source_unavailable" else "ambiguous"
    if verdict in DECIDED:
        return verdict
    return "ambiguous"


def _coverage(review_ids_csv: Path) -> None:
    counts: Counter = Counter()
    with open(review_ids_csv, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            counts[r["rule_name"]] += 1
    logger.info("per-rule sample sizes in %s (%d rules):", review_ids_csv.name, len(counts))
    for rule, n in counts.most_common():
        logger.info("  %5d  %s", n, rule)


def analyze(*, batch_dir: Path, verdicts_dir: Path) -> dict:
    manifest = json.loads((batch_dir / "cofire_manifest.json").read_text(encoding="utf-8"))

    # review_id -> (unit_key, degree, stratum, rule_name) from the sampled flags.
    rid_meta: dict[str, dict] = {}
    with open(batch_dir / "review_ids.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rid_meta[r["review_id"]] = {
                "rule_name": r["rule_name"],
                "stratum": r["stratum"],
                "cik": r["cik"],
                "report_date": r["report_date"],
            }
    # Attach degree from the manifest units.
    unit_degree = {(u["cik"], u["report_date"]): u["degree"] for u in manifest["units"]}
    for rid, m in rid_meta.items():
        m["degree"] = unit_degree.get((m["cik"], m["report_date"]), 0)

    # Pull verdict states for sampled review_ids.
    states: dict[str, str] = {}
    missing = 0
    for rid in rid_meta:
        v = _load_verdict(verdicts_dir / f"{rid}.json")
        if v is None:
            missing += 1
            continue
        states[rid] = _verdict_state(v)

    # ---- per-rule false-positive rate ----
    per_rule: dict[str, Counter] = defaultdict(Counter)
    for rid, st in states.items():
        per_rule[rid_meta[rid]["rule_name"]][st] += 1
    per_rule_rows = []
    for rule, c in sorted(per_rule.items(), key=lambda kv: -(kv[1]["real_error"] + kv[1]["false_alarm"])):
        n_dec = c["real_error"] + c["false_alarm"]
        p, lo, hi = wilson(c["false_alarm"], n_dec) if n_dec else (float("nan"), 0.0, 1.0)
        per_rule_rows.append({
            "rule_name": rule, "n_decided": n_dec,
            "real_error": c["real_error"], "false_alarm": c["false_alarm"],
            "ambiguous": c["ambiguous"], "auto_or_no_source": c["auto"] + c["no_source"],
            "fp_rate": "" if n_dec == 0 else f"{p:.4f}",
            "fp_lo": "" if n_dec == 0 else f"{lo:.4f}",
            "fp_hi": "" if n_dec == 0 else f"{hi:.4f}",
        })

    # ---- ensemble: does real-error likelihood rise with co-firing degree? ----
    # flag-level: real rate among decided flags, bucketed by the unit's stratum.
    # unit-level: fraction of sampled units with >=1 decided real_error flag, by stratum.
    by_stratum_flags: dict[str, Counter] = defaultdict(Counter)
    unit_real: dict[tuple, bool] = {}
    unit_stratum: dict[tuple, str] = {}
    for rid, st in states.items():
        m = rid_meta[rid]
        key = (m["cik"], m["report_date"])
        unit_stratum[key] = m["stratum"]
        if st in DECIDED:
            by_stratum_flags[m["stratum"]][st] += 1
            if st == "real_error":
                unit_real[key] = True
            else:
                unit_real.setdefault(key, False)

    order = ["d1", "d2_3", "d4_7", "d8plus"]
    degree_rows = []
    for s in order:
        c = by_stratum_flags.get(s, Counter())
        n_dec = c["real_error"] + c["false_alarm"]
        rp, rlo, rhi = wilson(c["real_error"], n_dec) if n_dec else (float("nan"), 0.0, 1.0)
        units_in_s = [k for k, v in unit_stratum.items() if v == s]
        n_units = len(units_in_s)
        any_real = sum(1 for k in units_in_s if unit_real.get(k))
        up, ulo, uhi = wilson(any_real, n_units) if n_units else (float("nan"), 0.0, 1.0)
        degree_rows.append({
            "stratum": s, "flags_decided": n_dec,
            "flag_real_rate": "" if n_dec == 0 else f"{rp:.4f}",
            "flag_real_lo": "" if n_dec == 0 else f"{rlo:.4f}",
            "flag_real_hi": "" if n_dec == 0 else f"{rhi:.4f}",
            "n_units": n_units, "units_any_real": any_real,
            "unit_any_real_rate": "" if n_units == 0 else f"{up:.4f}",
            "unit_any_real_lo": "" if n_units == 0 else f"{ulo:.4f}",
            "unit_any_real_hi": "" if n_units == 0 else f"{uhi:.4f}",
        })

    # ---- per-rule lift: real rate ALONE (degree 1) vs co-firing (degree >= 2) ----
    alone: dict[str, Counter] = defaultdict(Counter)
    cofire: dict[str, Counter] = defaultdict(Counter)
    for rid, st in states.items():
        if st not in DECIDED:
            continue
        m = rid_meta[rid]
        bucket = alone if m["degree"] <= 1 else cofire
        bucket[m["rule_name"]][st] += 1
    lift_rows = []
    for rule in sorted(set(alone) | set(cofire)):
        a, cf = alone[rule], cofire[rule]
        a_n, cf_n = a["real_error"] + a["false_alarm"], cf["real_error"] + cf["false_alarm"]
        a_real = (a["real_error"] / a_n) if a_n else None
        cf_real = (cf["real_error"] / cf_n) if cf_n else None
        lift_rows.append({
            "rule_name": rule,
            "alone_n": a_n, "alone_real_rate": "" if a_real is None else f"{a_real:.4f}",
            "cofire_n": cf_n, "cofire_real_rate": "" if cf_real is None else f"{cf_real:.4f}",
            "lift": "" if (a_real is None or cf_real is None) else f"{cf_real - a_real:+.4f}",
        })

    # ---- write outputs ----
    def _write(name, rows, cols):
        path = batch_dir / name
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        return path

    _write("per_rule_fp.csv", per_rule_rows,
           ["rule_name", "n_decided", "real_error", "false_alarm", "ambiguous",
            "auto_or_no_source", "fp_rate", "fp_lo", "fp_hi"])
    _write("ensemble_by_degree.csv", degree_rows,
           ["stratum", "flags_decided", "flag_real_rate", "flag_real_lo", "flag_real_hi",
            "n_units", "units_any_real", "unit_any_real_rate", "unit_any_real_lo", "unit_any_real_hi"])
    _write("rule_lift.csv", lift_rows,
           ["rule_name", "alone_n", "alone_real_rate", "cofire_n", "cofire_real_rate", "lift"])

    # markdown rollup
    n_states = Counter(states.values())
    md = ["# Ensemble + FP analysis", "",
          f"- sampled flags: {len(rid_meta)}; verdicts found: {len(states)}; missing: {missing}",
          f"- verdict mix: {dict(n_states)}", "",
          "## Real-error likelihood by co-firing degree", "",
          "| stratum | flags decided | flag real-rate [95% CI] | units | unit any-real rate [95% CI] |",
          "|---|---|---|---|---|"]
    for r in degree_rows:
        fr = "n/a" if r["flag_real_rate"] == "" else f'{float(r["flag_real_rate"]):.2f} [{float(r["flag_real_lo"]):.2f}, {float(r["flag_real_hi"]):.2f}]'
        ur = "n/a" if r["unit_any_real_rate"] == "" else f'{float(r["unit_any_real_rate"]):.2f} [{float(r["unit_any_real_lo"]):.2f}, {float(r["unit_any_real_hi"]):.2f}]'
        md.append(f'| {r["stratum"]} | {r["flags_decided"]} | {fr} | {r["n_units"]} | {ur} |')
    md += ["", "If flag real-rate and unit any-real rate climb monotonically with the",
           "stratum, co-firing is a stronger defect indicator than a single rule.", ""]
    (batch_dir / "ensemble_summary.md").write_text("\n".join(md), encoding="utf-8")

    return {
        "sampled_flags": len(rid_meta), "verdicts_found": len(states), "missing": missing,
        "verdict_mix": dict(n_states), "out_dir": str(batch_dir),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Ensemble + FP analysis for the weak-rule B1 experiment.")
    p.add_argument("--batch-id", default="ens1")
    p.add_argument("--verdicts-dir", type=Path, default=DEFAULT_VERDICTS)
    p.add_argument("--coverage", action="store_true",
                   help="Just report per-rule sample sizes from review_ids.csv and exit (no verdicts needed).")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    batch_dir = DEFAULT_OUT_BASE / args.batch_id
    if args.coverage:
        _coverage(batch_dir / "review_ids.csv")
        return 0

    res = analyze(batch_dir=batch_dir, verdicts_dir=args.verdicts_dir)
    logger.info("verdicts found %d/%d (missing %d); mix=%s",
                res["verdicts_found"], res["sampled_flags"], res["missing"], res["verdict_mix"])
    logger.info("wrote per_rule_fp.csv, ensemble_by_degree.csv, rule_lift.csv, ensemble_summary.md in %s", res["out_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
