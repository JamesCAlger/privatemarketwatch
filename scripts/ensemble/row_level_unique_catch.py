"""Row-level unique-catch analysis: is each KNOWN real row-level error found by a
high-FP rule also flagged, on the SAME ROW, by another (kept) rule?

Sharpens unique_catch_analysis.py (unit-level) to row granularity. For every
real-adjudicated flag of a high-FP rule we know the culprit row(s) from the B1
verdict leaf (culprit_citations + observed_value). row_validation_issues.csv
records per-rule firings keyed by (cik, report_date, row_key, column, value)
where row_key is the positional index of the prepared holdings frame -- shared
across all rules within one validation run, so same-row co-flagging is exact.

Culprit pinpointing: within the firing rule's flagged rows at the unit, the row
whose issue `value` matches the verdict's `observed_value`. When no value match
exists, we fall back to a bound: if ALL of the rule's flagged rows at the unit
are covered by kept rules, the culprit is covered whichever row it is.

Scope limits (reported, not hidden):
- fmt_* weak-engine rules have NO row-level firing artifact (shadow ledger is
  unit-level) -> excluded from strict row analysis.
- The issues file reflects the CURRENT frame; verdicts adjudicated on earlier
  eras may reference rows since corrected -> status rule_not_firing_now.
- Unit-level rules (fv_conservation, oracle A/B/E/F rules) cannot row-flag by
  construction; row-level coverage here credits ONLY row-granular rules. Their
  investigative coverage is the unit-level analysis' subject.

Inputs:
  data/output/ensemble/unique_catch/unique_catch_detail.csv  -- the 89 real flags
  data/output/review_queue/verdicts/<rid>.json               -- culprit values
  data/output/row_validation_issues.csv                      -- row-level firings

Outputs (data/output/ensemble/unique_catch/):
  row_level_detail.csv, row_level_per_rule.csv, row_level_summary.md

Read-only on inputs. ASCII-only logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

from pipeline import config
from scripts.ensemble.analyze_ensemble import _load_verdict

logger = logging.getLogger(__name__)

OUT_DIR = config.OUTPUT_DIR / "ensemble" / "unique_catch"
VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
ISSUES = config.OUTPUT_DIR / "row_validation_issues.csv"

HIGH_FP_RULES = {
    "X08", "C103", "C104", "C404", "C107", "X10", "PP01",
    "X01", "X07", "fmt_pct_of_net_assets", "fmt_basis_spread",
}
# No row-level firing artifact exists for these (weak engine -> unit-level ledger).
NOT_ROW_ASSESSABLE = {"fmt_pct_of_net_assets", "fmt_basis_spread"}

VALUE_TOL = 1.0  # issue `value` vs verdict observed_value


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _to_float(s) -> float | None:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _load_issues_for_units(units: set[tuple[str, str]]):
    """(cik10, report_date) -> row_key -> list of (rule_id, column, value_float)."""
    con = duckdb.connect()
    vals = ", ".join(f"('{c}', '{d}')" for c, d in sorted(units))
    q = f"""
        WITH target(cik, report_date) AS (VALUES {vals})
        SELECT lpad(ltrim(i.cik, '0'), 10, '0') AS cik10, i.report_date,
               i.row_key, i."column" AS col, i.rule_id, i.value
        FROM read_csv_auto('{ISSUES.as_posix()}', all_varchar=true) i
        JOIN target t ON lpad(ltrim(i.cik, '0'), 10, '0') = t.cik
                     AND i.report_date = t.report_date
        WHERE i.row_key IS NOT NULL AND i.row_key <> ''
    """
    rows = con.execute(q).fetchall()
    con.close()
    out: dict[tuple[str, str], dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for cik10, rd, row_key, col, rule_id, value in rows:
        out[(cik10, rd)][row_key].append((rule_id, col, _to_float(value)))
    return out


def analyze(out_dir: Path = OUT_DIR, verdicts_dir: Path = VERDICTS) -> dict:
    reals = _read_csv(out_dir / "unique_catch_detail.csv")
    logger.info("real flags of high-FP rules: %d", len(reals))

    units = {(r["cik"], r["report_date"]) for r in reals}
    issues = _load_issues_for_units(units)
    n_issue_rows = sum(len(v) for v in issues.values())
    logger.info("issue rows loaded for %d units: %d distinct row_keys",
                len(issues), n_issue_rows)

    detail_rows = []
    for r in reals:
        rule, rid = r["rule_name"], r["review_id"]
        unit = (r["cik"], r["report_date"])
        rec = {
            "rule_name": rule, "review_id": rid, "cik": r["cik"],
            "report_date": r["report_date"], "mechanism": r["mechanism"],
            "status": "", "n_rule_rows_now": 0, "n_rows_kept_covered": 0,
            "culprit_row_keys": "", "culprit_kept_covered": "",
            "culprit_covering_rules": "", "culprit_same_column_rules": "",
            "observed_value": "",
        }
        if rule in NOT_ROW_ASSESSABLE:
            rec["status"] = "no_row_artifact"
            detail_rows.append(rec)
            continue
        unit_rows = issues.get(unit, {})
        rule_rows = {rk: flags for rk, flags in unit_rows.items()
                     if any(f[0] == rule for f in flags)}
        rec["n_rule_rows_now"] = len(rule_rows)
        if not rule_rows:
            rec["status"] = "rule_not_firing_now"
            detail_rows.append(rec)
            continue

        def kept_rules_on(rk):
            return {f[0] for f in unit_rows.get(rk, [])
                    if f[0] != rule and f[0] not in HIGH_FP_RULES}

        covered = {rk for rk in rule_rows if kept_rules_on(rk)}
        rec["n_rows_kept_covered"] = len(covered)

        v = _load_verdict(verdicts_dir / f"{rid}.json") or {}
        obs = _to_float(v.get("observed_value"))
        rec["observed_value"] = "" if obs is None else obs
        culprits = []
        if obs is not None:
            for rk, flags in rule_rows.items():
                for (fr, _c, fv) in flags:
                    if fr == rule and fv is not None and abs(fv - obs) <= VALUE_TOL:
                        culprits.append(rk)
                        break
        if culprits:
            rec["status"] = "culprit_pinpointed"
            rec["culprit_row_keys"] = ";".join(culprits)
            cov = {rk: kept_rules_on(rk) for rk in culprits}
            rec["culprit_kept_covered"] = all(cov.values())
            rec["culprit_covering_rules"] = ";".join(sorted(set().union(*cov.values()))) \
                if any(cov.values()) else ""
            rule_cols = {c for rk in culprits
                         for (fr, c, _v) in rule_rows[rk] if fr == rule}
            same_col = {f[0] for rk in culprits for f in unit_rows.get(rk, [])
                        if f[0] != rule and f[0] not in HIGH_FP_RULES
                        and f[1] in rule_cols}
            rec["culprit_same_column_rules"] = ";".join(sorted(same_col))
        else:
            # bound: covered whichever row the culprit is iff ALL rows covered
            rec["status"] = "culprit_unmatched_bound"
            rec["culprit_kept_covered"] = (len(covered) == len(rule_rows))
        detail_rows.append(rec)

    # per-rule rollup
    per_rule = []
    by_rule = defaultdict(list)
    for d in detail_rows:
        by_rule[d["rule_name"]].append(d)
    for rule in sorted(by_rule):
        ds = by_rule[rule]
        pin = [d for d in ds if d["status"] == "culprit_pinpointed"]
        bound = [d for d in ds if d["status"] == "culprit_unmatched_bound"]
        cov_pin = [d for d in pin if d["culprit_kept_covered"] is True]
        cov_bound = [d for d in bound if d["culprit_kept_covered"] is True]
        uncovered = [d for d in pin + bound if d["culprit_kept_covered"] is not True]
        cover_freq = Counter()
        for d in cov_pin:
            cover_freq.update(d["culprit_covering_rules"].split(";"))
        per_rule.append({
            "rule_name": rule, "n_real": len(ds),
            "no_row_artifact": sum(d["status"] == "no_row_artifact" for d in ds),
            "not_firing_now": sum(d["status"] == "rule_not_firing_now" for d in ds),
            "culprit_pinpointed": len(pin), "bound_only": len(bound),
            "culprit_row_covered": len(cov_pin) + len(cov_bound),
            "culprit_row_uncovered": len(uncovered),
            "uncovered_rids": ";".join(d["review_id"] for d in uncovered),
            "top_covering_rules": ";".join(f"{k}:{n}" for k, n in
                                           cover_freq.most_common(5)),
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "row_level_detail.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(detail_rows[0]))
        w.writeheader()
        w.writerows(detail_rows)
    with open(out_dir / "row_level_per_rule.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_rule[0]))
        w.writeheader()
        w.writerows(per_rule)

    lines = [
        "# Row-level unique-catch analysis",
        "",
        "Question: for each KNOWN real row-level error (B1-adjudicated real flag of",
        "a high-FP rule), does another KEPT row-granular rule flag the SAME row_key?",
        "",
        "| rule | n_real | no artifact | not firing now | pinpointed | bound-only | row-covered | ROW-UNCOVERED |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in per_rule:
        lines.append(
            f"| {p['rule_name']} | {p['n_real']} | {p['no_row_artifact']} | "
            f"{p['not_firing_now']} | {p['culprit_pinpointed']} | {p['bound_only']} | "
            f"{p['culprit_row_covered']} | {p['culprit_row_uncovered']} |")
    lines += ["", "Uncovered culprits (verdict-known real rows NO kept rule flags):", ""]
    for p in per_rule:
        if p["culprit_row_uncovered"]:
            lines.append(f"- {p['rule_name']}: {p['uncovered_rids']}")
    lines += ["", "Caveats: unit-level rules (fv_conservation, oracle) cannot row-flag",
              "and get no credit here; fmt_* rules have no row artifact; verdicts",
              "from earlier eras may reference since-corrected rows (not_firing_now).", ""]
    (out_dir / "row_level_summary.md").write_text("\n".join(lines) + "\n",
                                                  encoding="utf-8")
    logger.info("wrote row_level_* to %s", out_dir)
    return {"per_rule": per_rule}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = p.parse_args()
    res = analyze(out_dir=args.out_dir)
    for r in res["per_rule"]:
        logger.info("%s: real %d, covered %d, UNCOVERED %d (pin %d, bound %d, "
                    "notfiring %d)", r["rule_name"], r["n_real"],
                    r["culprit_row_covered"], r["culprit_row_uncovered"],
                    r["culprit_pinpointed"], r["bound_only"], r["not_firing_now"])


if __name__ == "__main__":
    main()
