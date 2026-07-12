"""Retrospective re-cut of ens2 B1 adjudications by fingerprint group (rule_id, cik).

The spec (docs/weak_rule_remediation_architecture.md section 5) proposes an experiment
before adopting per-fingerprint stratification of B1 calibration: re-cut the existing
decided ens2 verdicts by fingerprint group and measure whether per-rule pooled real-rates
hide material per-group (per-CIK) variation. No new adjudications; read-only.

Measures, per rule:
  (a) dispersion  -- Monte Carlo chi-square of per-group real counts vs the rule's
      pooled rate (H0: every group draws from Binomial(n_j, p_pooled)). Small-n safe:
      the p-value is simulated, not asymptotic.
  (b) routing disagreement -- groups whose real-rate estimate would route differently
      than the rule's pooled rate under the spec's direct-dispatch boundary
      (real-rate >= 0.8 i.e. FP <= 0.2 -> direct to B2; else behind a gate).
      Two flavors: raw (n_j >= 5, point estimate crosses) and strict (Wilson 95% CI
      entirely on the other side). FV-weighted by the group's sampled fv_at_risk.
  (c) sufficiency -- per-group sample-size distribution (n>=10 / n>=5 / singletons).

CAVEATS (report honestly):
  - ens2 sampling was stratified by co-firing degree, not uniform over firings, so
    per-group rates are estimates of the SAMPLED pool's composition.
  - Review-lane queue rows carry NO fv_at_risk (verified: all 934 ens2 ids match the
    current queue, all with empty fv_at_risk_m). Weights use n_units (flagged rows per
    review_id) as the materiality proxy instead; FV weighting needs a rebuild-side
    join and is out of scope for the retrospective step.
  - strict disagreement requires n >= 3: with n=1-2 all-FA, the Wilson upper bound
    already sits below 0.8 (0.79 / 0.66), which is a sample-size artifact at this
    boundary, not evidence about the group.
  - B1 verdicts are per flag group (>=1 real row), not row-level truth.

Writes fingerprint_groups.csv + fingerprint_stratification_by_rule.csv to the ens2
batch dir. ASCII only. No network.
"""
from __future__ import annotations

import csv
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

BATCH = Path("data/output/ensemble/ens2")
VERDICTS = Path("data/output/review_queue/verdicts")
QUEUE = Path("data/output/review_queue/review_queue.csv")
DECIDED = {"real_error", "false_alarm"}
DIRECT_REAL_RATE = 0.8      # spec section 5: FP <= ~0.2 routes direct to B2
N_SIMS = 20000
SEED = 20260707


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def chisq(groups: list[tuple[int, int]], p: float) -> float:
    """Sum over groups of (r_j - n_j p)^2 / (n_j p (1-p))."""
    q = p * (1 - p)
    return sum((r - n * p) ** 2 / (n * q) for n, r in groups)


def mc_pvalue(groups: list[tuple[int, int]], p: float, rng: random.Random) -> float:
    """Monte Carlo p-value for the dispersion statistic under the binomial null."""
    obs = chisq(groups, p)
    ge = 0
    for _ in range(N_SIMS):
        sim = [(n, sum(1 for _ in range(n) if rng.random() < p)) for n, _ in groups]
        if chisq(sim, p) >= obs:
            ge += 1
    return (ge + 1) / (N_SIMS + 1)


def load_adjudications() -> list[dict]:
    with open(BATCH / "review_ids.csv", newline="", encoding="utf-8") as fh:
        meta = list(csv.DictReader(fh))
    units_by_id: dict[str, float] = {}
    with open(QUEUE, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rid = (r.get("review_id") or "").strip()
            try:
                units_by_id[rid] = float(r.get("n_units") or 0.0)
            except ValueError:
                units_by_id[rid] = 0.0
    out = []
    for m in meta:
        p = VERDICTS / f"{m['review_id']}.json"
        if not p.exists():
            continue
        try:
            v = json.load(open(p, encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        verdict = (v.get("verdict") or "").strip().lower()
        if verdict not in DECIDED:
            continue
        out.append({
            "review_id": m["review_id"], "rule": m["rule_name"],
            "cik": m["cik"].zfill(10), "report_date": m["report_date"],
            "real": 1 if verdict == "real_error" else 0,
            "units": units_by_id.get(m["review_id"], 0.0),
        })
    return out


def main() -> int:
    adj = load_adjudications()
    n_real = sum(a["real"] for a in adj)
    print(f"decided ens2 adjudications: {len(adj)} "
          f"(real={n_real}, fa={len(adj) - n_real})")

    # fingerprint group = (rule, cik)
    groups: dict[tuple, dict] = {}
    for a in adj:
        g = groups.setdefault((a["rule"], a["cik"]), {"n": 0, "r": 0, "units": 0.0})
        g["n"] += 1
        g["r"] += a["real"]
        g["units"] += a["units"]

    by_rule: dict[str, list] = defaultdict(list)
    for (rule, cik), g in groups.items():
        by_rule[rule].append({"cik": cik, **g})

    print(f"fingerprint groups (rule, cik): {len(groups)} across {len(by_rule)} rules")
    sizes = sorted(g["n"] for g in groups.values())
    print(f"group size: median={sizes[len(sizes) // 2]}, max={sizes[-1]}, "
          f"n>=10: {sum(1 for s in sizes if s >= 10)}, "
          f"n>=5: {sum(1 for s in sizes if s >= 5)}, "
          f"singletons: {sum(1 for s in sizes if s == 1)}")

    rng = random.Random(SEED)
    rule_rows, group_rows = [], []
    for rule in sorted(by_rule, key=lambda r: -sum(g["n"] for g in by_rule[r])):
        gs = by_rule[rule]
        n_tot = sum(g["n"] for g in gs)
        r_tot = sum(g["r"] for g in gs)
        p = r_tot / n_tot
        units_tot = sum(g["units"] for g in gs)
        pooled_route = "direct" if p >= DIRECT_REAL_RATE else "gated"

        # dispersion (only meaningful with >=2 groups and a non-degenerate pool)
        pval = None
        if len(gs) >= 2 and 0.0 < p < 1.0:
            pval = mc_pvalue([(g["n"], g["r"]) for g in gs], p, rng)

        raw_dis, strict_dis, units_dis = 0, 0, 0.0
        for g in gs:
            rate = g["r"] / g["n"]
            lo, hi = wilson(g["r"], g["n"])
            g_route_raw = "direct" if rate >= DIRECT_REAL_RATE else "gated"
            raw = g["n"] >= 5 and g_route_raw != pooled_route
            # strict: CI entirely on the other side of the boundary, n >= 3
            strict = g["n"] >= 3 and (
                (pooled_route == "gated" and lo >= DIRECT_REAL_RATE)
                or (pooled_route == "direct" and hi < DIRECT_REAL_RATE))
            if raw:
                raw_dis += 1
                units_dis += g["units"]
            if strict:
                strict_dis += 1
            group_rows.append({
                "rule": rule, "cik": g["cik"], "n": g["n"], "n_real": g["r"],
                "real_rate": round(rate, 3), "wilson_lo": round(lo, 3),
                "wilson_hi": round(hi, 3), "flagged_units": int(g["units"]),
                "pooled_real_rate": round(p, 3), "route_pooled": pooled_route,
                "route_raw": g_route_raw if g["n"] >= 5 else "",
                "raw_disagree": int(raw), "strict_disagree": int(strict),
            })
        rule_rows.append({
            "rule": rule, "n_decided": n_tot, "n_real": r_tot,
            "pooled_real_rate": round(p, 3), "n_groups": len(gs),
            "n_groups_ge5": sum(1 for g in gs if g["n"] >= 5),
            "n_groups_ge10": sum(1 for g in gs if g["n"] >= 10),
            "max_group_n": max(g["n"] for g in gs),
            "dispersion_mc_p": (round(pval, 4) if pval is not None else ""),
            "route_pooled": pooled_route,
            "raw_disagree_groups": raw_dis, "strict_disagree_groups": strict_dis,
            "units_sampled": int(units_tot),
            "units_raw_disagree": int(units_dis),
            "units_raw_disagree_share": (round(units_dis / units_tot, 3)
                                         if units_tot else ""),
        })
        flag = ""
        if pval is not None and pval < 0.05:
            flag = "  <-- OVERDISPERSED"
        print(f"{rule:28s} n={n_tot:4d} groups={len(gs):3d} (ge5={rule_rows[-1]['n_groups_ge5']}) "
              f"pooled_real={p:.2f} [{pooled_route}] "
              f"mc_p={pval if pval is not None else 'n/a'} "
              f"raw_dis={raw_dis} strict_dis={strict_dis} "
              f"units_dis={units_dis:.0f}/{units_tot:.0f}{flag}")

    # detail: every disagreeing group, for inspection
    dis = [r for r in group_rows if r["raw_disagree"] or r["strict_disagree"]]
    if dis:
        print("\ndisagreeing groups (raw: n>=5 point estimate crosses; "
              "strict: n>=3 Wilson CI on the other side):")
        for r in sorted(dis, key=lambda x: (x["rule"], -x["n"])):
            print(f"  {r['rule']:20s} cik={r['cik']} n={r['n']} real={r['n_real']} "
                  f"rate={r['real_rate']} CI=[{r['wilson_lo']},{r['wilson_hi']}] "
                  f"pooled={r['pooled_real_rate']} [{r['route_pooled']}] "
                  f"units={r['flagged_units']} "
                  f"{'RAW' if r['raw_disagree'] else ''}{'+' if r['raw_disagree'] and r['strict_disagree'] else ''}"
                  f"{'STRICT' if r['strict_disagree'] else ''}")

    with open(BATCH / "fingerprint_stratification_by_rule.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rule_rows[0].keys()))
        w.writeheader()
        w.writerows(rule_rows)
    group_rows.sort(key=lambda r: (r["rule"], -r["n"]))
    with open(BATCH / "fingerprint_groups.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(group_rows[0].keys()))
        w.writeheader()
        w.writerows(group_rows)
    print(f"\nwrote {BATCH / 'fingerprint_stratification_by_rule.csv'}")
    print(f"wrote {BATCH / 'fingerprint_groups.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
