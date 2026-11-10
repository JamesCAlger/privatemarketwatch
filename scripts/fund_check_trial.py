"""One-fund check run: which of a fund's ledger findings still fire on trial data.

Re-runs, for one fund, the rule engines that are plain functions of the holdings and the
fund financials, on a trial build (``rebuild_sample_trial.py``) and optionally a fund-level
trial (``fund_level_trial.py``), and compares the result with the fund's outstanding findings
in a findings ledger. Writes under ``scratch/trial_builds/<label>/checks_<cik>/`` only.

Engines re-run: row_validation (column contracts), oracle, conservation (fair value only).
Engines NOT re-run (reported as such, never as cleared): fund_financials, nonaccrual, identity,
weak, source reconciliation, position purity. A finding is "still fires" when its rule produces
a fail or warn for that fund and quarter on the trial data. That is stricter than the ledger:
the ledger only lists a warn when the same fund-quarter also has a tight failure.

    python scripts/fund_check_trial.py --label hps_fix3 --cik 0001838126 --fund-label nav_fix
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rebuild_sample_trial import TRIAL_ROOT, _protected_state  # noqa: E402

logger = logging.getLogger("fund_check_trial")
RESOLVED = frozenset({"adjudicated_false_alarm", "remediated_promoted", "resolved_upstream",
                      "gone_unadjudicated", "verdict_retired"})
RERUN_ENGINES = ("row_validation", "oracle", "conservation")
FIRING = ("fail", "warn")
# Engines whose stale inputs make a re-run unreliable for specific rules.
STALE_INPUT_RULES = frozenset({("oracle", "E07")})  # reads the production source-reconciliation detail


def _pad(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"[^0-9]", "", regex=True).str.zfill(10)


def _day(series: pd.Series) -> pd.Series:
    return series.astype(str).str[:10]


def row_validation_status(issues: pd.DataFrame) -> pd.DataFrame:
    """One row per (rule, quarter): fail if any FAIL-severity issue row, else warn."""
    if issues.empty:
        return pd.DataFrame(columns=["engine", "rule_name", "report_date", "status", "n"])
    work = issues.assign(report_date=_day(issues["report_date"]),
                         _fail=issues["severity"].astype(str).str.upper().eq("FAIL"))
    out = work.groupby(["rule_id", "report_date"]).agg(n=("rule_id", "size"), _fail=("_fail", "any")).reset_index()
    out["status"] = out["_fail"].map({True: "fail", False: "warn"})
    out["engine"] = "row_validation"
    return out.rename(columns={"rule_id": "rule_name"})[["engine", "rule_name", "report_date", "status", "n"]]


def conservation_status(holdings: pd.DataFrame, fund_financials: pd.DataFrame, band_pct: float) -> pd.DataFrame:
    """Published-basis fair value per quarter against the filed investments total."""
    published = holdings[holdings.get("accounting_record_class", "").astype(str) != "underlying_schedule"]
    total = (published.assign(d=_day(published["report_date"]), fv=pd.to_numeric(published["fair_value"], errors="coerce"))
             .groupby("d")["fv"].sum())
    filed = (fund_financials.assign(d=_day(fund_financials["report_date"]),
                                    f=pd.to_numeric(fund_financials["investments_at_fair_value"], errors="coerce"))
             .groupby("d")["f"].max())
    rows = []
    for quarter, fv in total.items():
        anchor = filed.get(quarter)
        if anchor is None or pd.isna(anchor) or anchor == 0:
            rows.append(("conservation", "fv_conservation", quarter, "skip", None))
            continue
        gap = 100 * (fv - anchor) / anchor
        rows.append(("conservation", "fv_conservation", quarter, "fail" if abs(gap) > band_pct else "pass", round(gap, 3)))
    return pd.DataFrame(rows, columns=["engine", "rule_name", "report_date", "status", "n"])


def column_contract_rule_ids() -> frozenset[str]:
    """Rule ids the column-contract validator can emit (other row rules come from adapters)."""
    import inspect
    import re

    from pipeline import column_validation
    source = inspect.getsource(column_validation.validate_column_contracts)
    return frozenset(re.findall(r'_issue_query\(\s*"[^"]+",\s*"([A-Z0-9_]+)"', source))


def compare(findings: pd.DataFrame, results: pd.DataFrame, row_rules=frozenset()) -> pd.DataFrame:
    """Label each outstanding finding: still_fires, no_longer_fires or not_rerun."""
    firing = {(r.engine, r.rule_name, r.report_date) for r in results.itertuples() if r.status in FIRING}
    ran = {(r.engine, r.rule_name) for r in results.itertuples()}
    out = findings.copy()

    def label(row):
        if row["engine"] not in RERUN_ENGINES or (row["engine"], row["rule_name"]) in STALE_INPUT_RULES:
            return "not_rerun"
        if (row["engine"], row["rule_name"], row["report_date"]) in firing:
            return "still_fires"
        # A rule that produced no row at all for the fund was either clean or not run; only
        # engines that emit every evaluated rule (oracle, conservation) can tell them apart.
        row_rule = row["engine"] == "row_validation"
        if (row_rule and row["rule_name"] in row_rules) or (
                not row_rule and (row["engine"], row["rule_name"]) in ran):
            return "no_longer_fires"
        return "not_rerun"

    out["trial"] = out.apply(label, axis=1)
    return out


def load_findings(ledger: Path, cik: str, since: str) -> pd.DataFrame:
    csv.field_size_limit(10**9)
    with open(ledger, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r["cik"].zfill(10) == cik and r["state"] not in RESOLVED
                and r["report_date"][:10] >= since]
    frame = pd.DataFrame(rows, columns=["review_id", "state", "engine", "rule_name", "report_date"])
    frame["report_date"] = _day(frame["report_date"])
    return frame


def run(label: str, cik: str, ledger: Path, fund_label: str | None, since: str) -> pd.DataFrame:
    from pipeline import column_validation, config, oracle_runner

    trial_dir = TRIAL_ROOT / label
    out_dir = trial_dir / ("checks_" + cik)
    out_dir.mkdir(parents=True, exist_ok=True)
    before = _protected_state(config.OUTPUT_DIR)
    holdings = pd.read_csv(trial_dir / "private_markets_holdings.csv", dtype=str)
    holdings = holdings[_pad(holdings["cik"]).eq(cik)].copy()
    holdings_file = out_dir / "holdings.csv"
    holdings.to_csv(holdings_file, index=False)
    financials = pd.read_csv(config.FUND_FINANCIALS_FILE, dtype=str)
    financials = financials[_pad(financials["cik"]).eq(cik)].copy()
    if fund_label:
        trial_fin = pd.read_csv(TRIAL_ROOT / (fund_label + "_fund") / "fund_financials_bdc.csv", dtype=str)
        trial_fin = trial_fin[_pad(trial_fin["cik"]).eq(cik)].set_index("report_date")
        for column in ("nav_per_share", "net_assets", "shares_outstanding"):
            if column in trial_fin:
                mapped = financials["report_date"].map(trial_fin[column])
                financials[column] = mapped.where(financials["report_date"].isin(trial_fin.index), financials[column])
    financials_file = out_dir / "fund_financials.csv"
    financials.to_csv(financials_file, index=False)

    issues, _ = column_validation.validate_column_contracts(holdings)
    issues.to_csv(out_dir / "row_validation_issues.csv", index=False)
    with patch.object(oracle_runner, "UNIFIED_HOLDINGS_FILE", holdings_file), \
         patch.object(oracle_runner, "FUND_FINANCIALS_FILE", financials_file):
        oracle_runner.run_oracle(cik=cik, output_dir=out_dir / "oracle")
    oracle = pd.read_csv(out_dir / "oracle" / "check_results.csv", dtype=str)
    oracle = oracle[oracle["report_date"].notna()]
    oracle_status = pd.DataFrame(dict(engine="oracle", rule_name=oracle["check_id"], report_date=_day(oracle["report_date"]),
                                      status=oracle["status"].str.lower(), n=oracle["metric_value"]))
    results = pd.concat([row_validation_status(issues), oracle_status,
                         conservation_status(holdings, financials, config.FV_CONSERVATION_BAND_PCT)], ignore_index=True)
    results.to_csv(out_dir / "check_results.csv", index=False)
    compared = compare(load_findings(ledger, cik, since), results, column_contract_rule_ids())
    compared.to_csv(out_dir / "findings_vs_trial.csv", index=False)
    after = _protected_state(config.OUTPUT_DIR)
    touched = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
    if touched:
        raise RuntimeError("check trial changed production files: " + ", ".join(touched))
    return compared


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True, help="trial build under scratch/trial_builds")
    parser.add_argument("--cik", required=True)
    parser.add_argument("--fund-label", help="fund-level trial whose NAV fields replace the published ones")
    parser.add_argument("--ledger", type=Path,
                        default=ROOT / "data/output/quarter_pass/q1p3_20260831/findings_ledger_post.csv")
    parser.add_argument("--since", default="2022-01-01")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    cik = str(args.cik).zfill(10)
    compared = run(args.label, cik, args.ledger, args.fund_label, args.since)
    print("outstanding findings for %s since %s in %s: %d" % (cik, args.since, args.ledger.parent.name, len(compared)))
    print("  " + " | ".join("%s %d" % kv for kv in Counter(compared["trial"]).most_common()))
    print("engine | rule | still fires | no longer fires | not re-run")
    table = compared.groupby(["engine", "rule_name"])["trial"].value_counts().unstack(fill_value=0)
    for (engine, rule), row in table.iterrows():
        print("   %s | %s | %d | %d | %d" % (engine, rule, row.get("still_fires", 0), row.get("no_longer_fires", 0),
                                              row.get("not_rerun", 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
