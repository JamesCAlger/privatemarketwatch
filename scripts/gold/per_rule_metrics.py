"""Per-rule precision + per-error-type recall against the frozen gold sample.

The aggregate estimator (estimate_gold.py) scores the WHOLE surfaced/suppressed
population at once. This scores the panel RULE-BY-RULE, so each rule has its own
prediction set frozen against the gold sample and gets its own precision/recall the
moment labels exist. Runs now on partial gold: what is computable today is computed;
what needs labels that do not exist yet is reported as 'pending' (not faked).

Two metrics, two grains, two data sources -- by necessity, not choice:

  PRECISION (per rule)        needs a per-FLAG verdict (real_error/false_alarm). Those
                              live in flag_labels.jsonl. The flag strata are DRAWN
                              (40 surfaced + 161 suppressed) but not yet adjudicated, so
                              today every rule's precision is 'pending' with its drawn-
                              but-unlabeled backlog shown. Wired and ready.

  RECALL (per error type,     needs gold units with a TRUE error of a known type and a
   per-rule contribution)     check of whether a rule of that type fired on the unit.
                              The 132 position labels carry true_fair_value / true_cost /
                              true_classification / true_lien / disposition, so recall is
                              LIVE today for those error types. Grain is cik-quarter
                              COVERAGE (a position error is 'covered' if a type-matched
                              rule fired anywhere in its cik-quarter) -- an UPPER BOUND on
                              true position-level recall, stated honestly.

Recall uses the sample design weights (1/pi, Horvitz-Thompson) so the tail census does
not swamp the body/silent strata; raw counts + Wilson CI are reported alongside.

The rule -> error-type map (RULE_FAMILY) is the one piece of judgement here; it is an
explicit, editable data dict with a one-line rationale per family. Unmapped engines are
listed, never silently credited. Refine it as rules are added.

READ-ONLY except a summary JSON under data/gold/. No network, no pipeline outputs touched.

Usage: python scripts/gold/per_rule_metrics.py --draw batch1
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estimate_gold as eg  # noqa: E402  (reuse wilson / pos_error / loaders)

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "data" / "gold" / "labels"
LEDGER = ROOT / "data" / "output" / "shadow" / "validation_results_ledger.csv"

# --------------------------------------------------------------------------- #
# Rule -> error-type correspondence. A rule can only be CREDITED with catching an
# error of the type it actually targets. Mapped by ENGINE (coarse) with rule-name
# overrides (fine). Only error types for which the gold carries truth today are
# scoreable; the rest are declared so coverage gaps are visible, not hidden.
#   fair_value     : reconciles position/total FV vs an independent anchor.
#   cost           : reconciles summed cost vs companyfacts InvestmentOwnedAtCost.
#   classification : asset-class / index-classification correctness.
#   lien           : lien-tier correctness.   (no rule targets it -> recall exposes gap)
#   over_inclusion : subtotal/aggregate/comparative rows leaking in as positions.
# --------------------------------------------------------------------------- #
FAMILY_ENGINES = {
    # FV detectors = engines that reconcile position/total FV against an INDEPENDENT
    # anchor. 'oracle' is deliberately EXCLUDED: its per-CIK extraction-QA rules fire on
    # nearly every cik-quarter, so crediting them makes coverage trivially 1.0 (ambient
    # presence, not detection). Add it back only if a specific oracle rule is shown to be
    # an FV-error detector.
    "fair_value": {"conservation", "gav_recon", "source_recon", "html_extract",
                   "aggregate_header"},
    "cost": set(),                       # cost_conservation rule only (override below)
    "classification": {"classification", "derivative_role", "fund_strategy"},
    "lien": set(),                       # intentionally empty: no lien rule exists yet
    "over_inclusion": {"aggregate_header"},
}
RULE_OVERRIDE = {                        # rule_name -> error_type (wins over engine)
    "cost_conservation": "cost",
    "agentA_subtotal_candidate": "over_inclusion",
    "R07": "fair_value", "E02": "fair_value",   # positions FV > fund total assets
}
SCOREABLE = ["fair_value", "cost", "classification", "lien", "over_inclusion"]
_OVERINCLUSION_DISPOSITIONS = {"aggregate_subtotal", "look_through", "comparative", "non_position"}


def _error_type(engine: str, rule_name: str) -> str | None:
    if rule_name in RULE_OVERRIDE:
        return RULE_OVERRIDE[rule_name]
    for et, engines in FAMILY_ENGINES.items():
        if engine in engines:
            return et
    return None


def fired_flags() -> list[dict]:
    """Distinct (cik, period, engine, rule_name) the panel flagged (status fail|warn)."""
    if not LEDGER.exists():
        return []
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT DISTINCT
            lpad(cast(try_cast(cik AS BIGINT) AS VARCHAR), 10, '0') AS cik,
            cast(period AS VARCHAR) AS period,
            cast(engine AS VARCHAR) AS engine,
            cast(rule_name AS VARCHAR) AS rule_name
        FROM read_csv_auto('{LEDGER.as_posix()}', sample_size=-1, all_varchar=true)
        WHERE lower(status) IN ('fail', 'warn')
          AND try_cast(cik AS BIGINT) IS NOT NULL
        """
    ).fetchdf().to_dict("records")
    con.close()
    return rows


def _disposition_error(lbl: dict) -> bool:
    """A confirmed over-inclusion row (subtotal / look-through / comparative / non-position)."""
    return str(lbl.get("disposition") or "valid") in _OVERINCLUSION_DISPOSITIONS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", default="batch1")
    args = ap.parse_args()

    frame = eg.load_frame(args.draw)
    pos = eg.load_labels(LABELS / "position_labels.jsonl")
    flag_labels = eg.load_labels(LABELS / "flag_labels.jsonl")

    fired = fired_flags()
    # (cik, period) sets a given error type has ANY matching rule fired on, and per-rule
    fired_by_type: dict[str, set] = defaultdict(set)
    fired_by_rule: dict[str, set] = defaultdict(set)         # rule_name -> {(cik,period)}
    rules_in_type: dict[str, set] = defaultdict(set)         # error_type -> {rule_name}
    for f in fired:
        et = _error_type(f["engine"], f["rule_name"])
        if et is None:
            continue
        key = (f["cik"], f["period"])
        fired_by_type[et].add(key)
        fired_by_rule[f["rule_name"]].add(key)
        rules_in_type[et].add(f["rule_name"])

    report: dict = {"draw": args.draw, "n_position_labels": len(pos),
                    "n_flag_labels": len(flag_labels),
                    "family_engines": {k: sorted(v) for k, v in FAMILY_ENGINES.items()},
                    "rule_override": RULE_OVERRIDE}

    # ---------------- RECALL (live from position labels) ---------------------
    # A position label is a "positive" for error type T if its source-truth field
    # disagrees with the pipeline (FV/cost/class/lien) or its disposition is an
    # over-inclusion. Covered if a type-T rule fired on its cik-quarter.
    recall: dict = {}
    for et in SCOREABLE:
        pos_units, weighted = [], []     # (covered:bool, pi)
        for lbl in pos:
            fr = frame.get(lbl["_key"])
            if not fr:
                continue
            cik, period = lbl.get("cik"), lbl.get("report_date")
            if et == "over_inclusion":
                is_pos = _disposition_error(lbl)
            else:
                pe = eg.pos_error(lbl, fr)
                is_pos = pe["checked"].get(et) and pe["errs"].get(et)
            if not is_pos:
                continue
            covered = (cik, period) in fired_by_type.get(et, set())
            pi = fr.get("pi") or 1.0
            pos_units.append(covered)
            weighted.append((covered, pi))
        n = len(pos_units)
        k = sum(1 for c in pos_units if c)
        p, lo, hi = eg.wilson(k, n)
        w_tot = sum(1.0 / pi for _, pi in weighted) or 0.0
        w_cov = sum(1.0 / pi for c, pi in weighted if c)
        # per-rule contribution within this error type
        contrib = {}
        for rule in sorted(rules_in_type.get(et, set())):
            ck = sum(1 for lbl in pos
                     if frame.get(lbl["_key"])
                     and ((_disposition_error(lbl) if et == "over_inclusion"
                           else (eg.pos_error(lbl, frame[lbl["_key"]])["checked"].get(et)
                                 and eg.pos_error(lbl, frame[lbl["_key"]])["errs"].get(et)))
                          and (lbl.get("cik"), lbl.get("report_date")) in fired_by_rule.get(rule, set())))
            if ck:
                contrib[rule] = ck
        recall[et] = {
            "positives": n, "covered": k,
            "recall_raw": None if n == 0 else round(p, 3),
            "ci95": [round(lo, 3), round(hi, 3)] if n else None,
            "recall_ht_weighted": None if w_tot == 0 else round(w_cov / w_tot, 3),
            "rules_credited": sorted(rules_in_type.get(et, set())),
            "per_rule_covered": contrib,
            "note": ("no rule targets this error type -- recall is a coverage gap"
                     if not rules_in_type.get(et) else "cik-quarter coverage (upper bound)"),
        }
    report["recall_by_error_type"] = recall

    # ---------------- PRECISION (per rule; pending until flags labeled) -------
    # Drawn-but-unlabeled backlog per rule, from the flag strata of the frame.
    drawn = defaultdict(lambda: {"surfaced_flag": 0, "suppressed_flag": 0})
    for r in frame.values():
        if r.get("unit_type") == "flag":
            rn = (r.get("flag") or {}).get("rule_name", "?")
            drawn[rn][r["stratum"]] += 1
    # verdicts where present
    verd = defaultdict(lambda: {"real_error": 0, "false_alarm": 0, "ambiguous": 0})
    for fl in flag_labels:
        fr = frame.get(fl["_key"])
        if not fr:
            continue
        rn = (fr.get("flag") or {}).get("rule_name", "?")
        v = fl.get("verdict")
        if v in verd[rn]:
            verd[rn][v] += 1
    precision = {}
    for rn in sorted(set(drawn) | set(verd)):
        real, false = verd[rn]["real_error"], verd[rn]["false_alarm"]
        decided = real + false
        p, lo, hi = eg.wilson(real, decided)
        precision[rn] = {
            "drawn_surfaced": drawn[rn]["surfaced_flag"],
            "drawn_suppressed": drawn[rn]["suppressed_flag"],
            "labeled": decided + verd[rn]["ambiguous"],
            "real_error": real, "false_alarm": false, "ambiguous": verd[rn]["ambiguous"],
            "precision": "pending" if decided == 0 else round(p, 3),
            "ci95": None if decided == 0 else [round(lo, 3), round(hi, 3)],
        }
    report["precision_by_rule"] = precision

    out = ROOT / "data" / "gold" / f"per_rule_metrics_{args.draw}.json"
    out.write_text(json.dumps(report, indent=2), encoding="ascii")

    # ---------------- console ------------------------------------------------
    print(f"[per-rule] draw={args.draw}  position_labels={len(pos)}  flag_labels={len(flag_labels)}")
    print(f"[per-rule] fired flag groups (fail|warn) mapped to an error type: "
          f"{sum(len(v) for v in fired_by_type.values())}")
    print("\nRECALL by error type  (gold positives -> covered by a type-matched rule):")
    print(f"  {'error_type':14s} {'pos':>4} {'cov':>4} {'recall':>7} {'HT_wtd':>7}  rules")
    for et in SCOREABLE:
        r = recall[et]
        rr = "n/a" if r["recall_raw"] is None else f"{r['recall_raw']:.3f}"
        ht = "n/a" if r["recall_ht_weighted"] is None else f"{r['recall_ht_weighted']:.3f}"
        rules = ",".join(r["rules_credited"]) or "(none)"
        print(f"  {et:14s} {r['positives']:>4} {r['covered']:>4} {rr:>7} {ht:>7}  {rules[:60]}")
        if r["per_rule_covered"]:
            for rule, ck in sorted(r["per_rule_covered"].items(), key=lambda x: -x[1]):
                print(f"      - {rule:40s} covers {ck}")
    print("\nPRECISION by rule  (pending until the drawn flag strata are adjudicated):")
    pend = [rn for rn, v in precision.items() if v["precision"] == "pending"
            and (v["drawn_surfaced"] or v["drawn_suppressed"])]
    print(f"  {len(pend)} rules have drawn-but-unlabeled flags; label flag_labels.jsonl to score them.")
    for rn in sorted(pend, key=lambda r: -(precision[r]["drawn_surfaced"]
                                           + precision[r]["drawn_suppressed"]))[:15]:
        v = precision[rn]
        print(f"      - {rn:40s} drawn surf={v['drawn_surfaced']:>2} supp={v['drawn_suppressed']:>2}  "
              f"precision={v['precision']}")
    print(f"\n[per-rule] wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
