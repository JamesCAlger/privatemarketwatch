"""Recalibration analysis for a draw_recal_batch frame (recal1+).

Unlike analyze_ensemble (which needs the co-firing manifest and degree strata --
the ensemble hypothesis was already tested and rejected on ens2), a recal frame
answers one question: WHAT ARE THE PER-RULE / PER-GROUP REAL-vs-FALSE-ALARM
RATES ON THE CURRENT (post-Wave-1) FRAME, and which of them SHIFTED vs the ens2
priors?

Inputs (batch dir = data/output/ensemble/<batch>):
  review_ids.csv           -- the drawn frame (review_id, cik, report_date,
                              engine, rule_name, fingerprint, quota_source, era)
  passstamp_carryover.csv  -- prior decided verdicts whose flags survived the
                              rebuild exactly (pass_stamped=true) -- credited
                              into the combined per-rule rates
  recal_manifest.json      -- divergent fingerprint groups under test
  data/output/review_queue/verdicts/<rid>.json  -- B1 verdict leaves
  data/output/ensemble/<prior-batch>/per_rule_fp.csv -- the priors (default ens2)

Outputs (batch dir): recal_per_rule.csv, recal_per_group.csv, recal_summary.md.

A rule/group is marked `shifted` when its combined Wilson 95% CI is DISJOINT
from the prior's CI -- a conservative flag; overlapping CIs say "no evidence of
change", not "unchanged". Read-only on verdicts. ASCII-only.
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
from scripts.ensemble.analyze_ensemble import _load_verdict, _verdict_state

logger = logging.getLogger(__name__)

OUT_BASE = config.OUTPUT_DIR / "ensemble"
VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
DECIDED = {"real_error", "false_alarm"}


def _ci(fa: int, n: int) -> tuple[float, float, float]:
    return wilson(fa, n) if n else (float("nan"), 0.0, 1.0)


def _fmt(x: float) -> str:
    return "" if x != x else f"{x:.4f}"  # NaN-safe


def _disjoint(lo1: float, hi1: float, lo2: float, hi2: float) -> bool:
    return lo1 > hi2 or hi1 < lo2


def analyze(*, batch_dir: Path, verdicts_dir: Path = VERDICTS,
            prior_batch: str = "ens2") -> dict:
    manifest = json.loads((batch_dir / "recal_manifest.json").read_text(encoding="utf-8-sig"))
    divergent = set(manifest.get("divergent_groups", []))

    # --- new-era verdicts over the drawn frame ---
    frame: list[dict] = []
    with open(batch_dir / "review_ids.csv", newline="", encoding="utf-8-sig") as fh:
        frame = list(csv.DictReader(fh))
    states: dict[str, str] = {}
    missing = 0
    for r in frame:
        v = _load_verdict(verdicts_dir / f"{r['review_id']}.json")
        if v is None:
            missing += 1
        else:
            states[r["review_id"]] = _verdict_state(v)

    new_rule: dict[str, Counter] = defaultdict(Counter)
    new_group: dict[str, Counter] = defaultdict(Counter)
    for r in frame:
        st = states.get(r["review_id"])
        if st is None:
            continue
        new_rule[r["rule_name"]][st] += 1
        new_group[r["fingerprint"]][st] += 1

    # --- carry-over: pass-stamped prior verdicts still valid on this frame ---
    carry_rule: dict[str, Counter] = defaultdict(Counter)
    carry_group: dict[str, Counter] = defaultdict(Counter)
    carry_path = batch_dir / "passstamp_carryover.csv"
    n_carry = 0
    if carry_path.exists():
        with open(carry_path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("pass_stamped", "")).lower() != "true":
                    continue
                verdict = (r.get("verdict") or "").strip().lower()
                if verdict not in DECIDED:
                    continue
                carry_rule[r["rule_name"]][verdict] += 1
                carry_group[r.get("fingerprint", "")][verdict] += 1
                n_carry += 1

    # --- priors ---
    prior: dict[str, dict] = {}
    prior_path = OUT_BASE / prior_batch / "per_rule_fp.csv"
    if prior_path.exists():
        with open(prior_path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                prior[r["rule_name"]] = r
    else:
        logger.warning("prior table missing (%s); delta columns empty", prior_path)

    # --- per-rule table ---
    rule_rows = []
    for rule in sorted(set(new_rule) | set(carry_rule)):
        nc, cc = new_rule[rule], carry_rule[rule]
        n_new = nc["real_error"] + nc["false_alarm"]
        comb_fa = nc["false_alarm"] + cc["false_alarm"]
        comb_n = n_new + cc["real_error"] + cc["false_alarm"]
        np_, nlo, nhi = _ci(nc["false_alarm"], n_new)
        cp, clo, chi = _ci(comb_fa, comb_n)
        pr = prior.get(rule)
        shifted = ""
        delta = ""
        if pr and pr.get("fp_rate") not in (None, "") and comb_n:
            plo, phi = float(pr["fp_lo"]), float(pr["fp_hi"])
            delta = f"{cp - float(pr['fp_rate']):+.4f}"
            shifted = "yes" if _disjoint(clo, chi, plo, phi) else "no"
        rule_rows.append({
            "rule_name": rule,
            "n_new_decided": n_new, "new_real": nc["real_error"],
            "new_fa": nc["false_alarm"], "new_ambiguous": nc["ambiguous"],
            "new_fp_rate": _fmt(np_), "new_fp_lo": _fmt(nlo), "new_fp_hi": _fmt(nhi),
            "carry_n": cc["real_error"] + cc["false_alarm"],
            "comb_n_decided": comb_n,
            "comb_fp_rate": _fmt(cp), "comb_fp_lo": _fmt(clo), "comb_fp_hi": _fmt(chi),
            "prior_n": (pr or {}).get("n_decided", ""),
            "prior_fp_rate": (pr or {}).get("fp_rate", ""),
            "delta_fp": delta, "shifted": shifted,
        })
    rule_rows.sort(key=lambda r: -r["comb_n_decided"])

    # --- per-group table (rule|cik fingerprints) ---
    group_rows = []
    for fp in sorted(set(new_group) | divergent):
        nc, cc = new_group[fp], carry_group[fp]
        n_new = nc["real_error"] + nc["false_alarm"]
        comb_n = n_new + cc["real_error"] + cc["false_alarm"]
        comb_fa = nc["false_alarm"] + cc["false_alarm"]
        cp, clo, chi = _ci(comb_fa, comb_n)
        group_rows.append({
            "fingerprint": fp, "divergent_under_test": "yes" if fp in divergent else "",
            "n_new_decided": n_new, "new_real": nc["real_error"], "new_fa": nc["false_alarm"],
            "carry_n": cc["real_error"] + cc["false_alarm"],
            "comb_n_decided": comb_n,
            "comb_fp_rate": _fmt(cp), "comb_fp_lo": _fmt(clo), "comb_fp_hi": _fmt(chi),
        })
    group_rows.sort(key=lambda r: (-(r["divergent_under_test"] == "yes"), -r["comb_n_decided"]))

    def _write(name: str, rows: list[dict], cols: list[str]) -> Path:
        path = batch_dir / name
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        return path

    _write("recal_per_rule.csv", rule_rows, list(rule_rows[0].keys()) if rule_rows else ["rule_name"])
    _write("recal_per_group.csv", group_rows, list(group_rows[0].keys()) if group_rows else ["fingerprint"])

    # --- markdown rollup ---
    mix = Counter(states.values())
    shifted_rules = [r for r in rule_rows if r["shifted"] == "yes"]
    md = [f"# Recalibration analysis -- {batch_dir.name} (era {manifest.get('era')})", "",
          f"- frame: {len(frame)} review_ids; verdicts found {len(states)}, missing {missing}",
          f"- verdict mix: {dict(mix)}",
          f"- carry-over credited: {n_carry} pass-stamped prior verdicts",
          f"- priors: {prior_batch} ({len(prior)} rules)", "",
          "## Rules whose combined FP rate SHIFTED vs prior (95% CIs disjoint)", "",
          "| rule | prior fp (n) | recal fp [95% CI] (n) | delta |", "|---|---|---|---|"]
    for r in shifted_rules:
        md.append(f"| {r['rule_name']} | {r['prior_fp_rate']} ({r['prior_n']}) "
                  f"| {r['comb_fp_rate']} [{r['comb_fp_lo']}, {r['comb_fp_hi']}] "
                  f"({r['comb_n_decided']}) | {r['delta_fp']} |")
    if not shifted_rules:
        md.append("(none)")
    md += ["", "## Divergent fingerprint groups under test", "",
           "| group | new n | new real | new fa | carry n | comb fp [95% CI] |", "|---|---|---|---|---|---|"]
    for g in group_rows:
        if g["divergent_under_test"] != "yes":
            continue
        md.append(f"| {g['fingerprint']} | {g['n_new_decided']} | {g['new_real']} | {g['new_fa']} "
                  f"| {g['carry_n']} | {g['comb_fp_rate']} [{g['comb_fp_lo']}, {g['comb_fp_hi']}] |")
    md.append("")
    (batch_dir / "recal_summary.md").write_text("\n".join(md), encoding="utf-8")

    return {"frame": len(frame), "verdicts": len(states), "missing": missing,
            "mix": dict(mix), "carry": n_carry, "shifted_rules": [r["rule_name"] for r in shifted_rules],
            "out_dir": str(batch_dir)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Recalibration (era-vs-prior) analysis for a recal frame.")
    p.add_argument("--batch-id", default="recal1")
    p.add_argument("--prior-batch", default="ens2")
    p.add_argument("--verdicts-dir", type=Path, default=VERDICTS)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    res = analyze(batch_dir=OUT_BASE / args.batch_id, verdicts_dir=args.verdicts_dir,
                  prior_batch=args.prior_batch)
    logger.info("frame %d, verdicts %d (missing %d), mix=%s, carry-over %d",
                res["frame"], res["verdicts"], res["missing"], res["mix"], res["carry"])
    logger.info("shifted rules vs prior: %s", ", ".join(res["shifted_rules"]) or "(none)")
    logger.info("wrote recal_per_rule.csv, recal_per_group.csv, recal_summary.md in %s", res["out_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
