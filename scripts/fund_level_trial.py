"""Fund-level trial: rebuild the highlights extract and the BDC fund financials for a few funds.

The fund-level counterpart of ``rebuild_sample_trial.py``. Reads cached filings and cached
company facts only (no downloads), writes under ``scratch/trial_builds/<label>_fund/`` and
never touches ``data/output``. Prints, per fund-quarter, the published NAV per share next to
the trial value and the NAV identity (nav_per_share * shares_outstanding vs net_assets).

    python scripts/fund_level_trial.py --label nav_fix --ciks 0001838126
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rebuild_sample_trial import TRIAL_ROOT, _protected_state, default_ciks  # noqa: E402

logger = logging.getLogger("fund_level_trial")
IDENTITY_TOL = 0.02


def _pad(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"[^0-9]", "", regex=True).str.zfill(10)


def nav_report(published: pd.DataFrame, trial: pd.DataFrame) -> pd.DataFrame:
    """One row per fund-quarter: published and trial NAV per share, and the trial identity gap."""
    keys = ["cik", "report_date"]
    left = published.assign(cik=_pad(published["cik"]))[keys + ["nav_per_share"]].rename(
        columns={"nav_per_share": "published_nav"})
    right = trial.assign(cik=_pad(trial["cik"]))[keys + ["nav_per_share", "net_assets", "shares_outstanding"]]
    out = right.merge(left, on=keys, how="left")
    for col in ("published_nav", "nav_per_share", "net_assets", "shares_outstanding"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["identity_gap_pct"] = (100 * (out["nav_per_share"] * out["shares_outstanding"] - out["net_assets"])
                               / out["net_assets"]).round(2)
    out["identity_ok"] = out["identity_gap_pct"].abs() <= 100 * IDENTITY_TOL
    return out.sort_values(keys)[keys + ["published_nav", "nav_per_share", "identity_gap_pct", "identity_ok"]]


def build(label: str, ciks: list[str]) -> Path:
    from pipeline import bdc_fund_highlights, config, extract_companyfacts, fund_financials
    from pipeline.fund_highlights_wrapper import class_nav_ciks

    run_dir = TRIAL_ROOT / (label + "_fund")
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    before = _protected_state(config.OUTPUT_DIR)
    t0 = time.time()
    index = pd.read_csv(config.BDC_FILINGS_INDEX_FILE, dtype=str)
    index = index[_pad(index["cik"]).isin(ciks)]
    highlights_file = run_dir / "bdc_fund_highlights.csv"
    with patch.object(bdc_fund_highlights, "BDC_FUND_HIGHLIGHTS_FILE", highlights_file):
        highlights = bdc_fund_highlights.extract_bdc_fund_highlights(filings_index=index)
    highlights = pd.read_csv(highlights_file, dtype=str)
    balance = extract_companyfacts._extract_all_companyfacts(
        ciks, client=None, companyfacts_cache_dir=config.COMPANYFACTS_CACHE_DIR)
    income = (pd.read_csv(config.BDC_FUND_INCOME_FILE, dtype=str)
              if config.BDC_FUND_INCOME_FILE.exists() else pd.DataFrame())
    if not income.empty:
        income = income[_pad(income["cik"]).isin(ciks)]
    consensus = fund_financials.class_nav_consensus(highlights, class_nav_ciks())
    trial = fund_financials._prepare_bdc(balance, income, class_nav_df=consensus)
    trial.to_csv(run_dir / "fund_financials_bdc.csv", index=False)
    consensus.to_csv(run_dir / "class_nav_consensus.csv", index=False)
    published = pd.read_csv(config.FUND_FINANCIALS_FILE, dtype=str)
    published = published[_pad(published["cik"]).isin(ciks)]
    report = nav_report(published, trial)
    report.to_csv(run_dir / "nav_report.csv", index=False)
    after = _protected_state(config.OUTPUT_DIR)
    touched = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
    if touched:
        raise RuntimeError("fund-level trial changed production files: " + ", ".join(touched))
    logger.info("fund-level trial %s: %d funds, %d filings, %d highlight rows, %d fund-quarters in %.0f s -> %s",
                label, len(ciks), len(index), len(highlights), len(trial), time.time() - t0, run_dir)
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--ciks", nargs="*", help="default: the acceptance findings scope")
    parser.add_argument("--since", default="2022-01-01", help="first report_date to print")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    logger.setLevel(logging.INFO)
    ciks = [str(c).zfill(10) for c in args.ciks] if args.ciks else default_ciks()
    run_dir = build(args.label, ciks)
    report = pd.read_csv(run_dir / "nav_report.csv", dtype={"cik": str})
    report = report[report["report_date"] >= args.since]
    print("cik | quarter | published NAV/share | trial NAV/share | identity gap pct | identity ok")
    for row in report.itertuples(index=False):
        print("   " + " | ".join("" if pd.isna(v) else str(v) for v in row))
    changed = report[~((report["published_nav"] - report["nav_per_share"]).abs() < 1e-9)
                     & ~(report["published_nav"].isna() & report["nav_per_share"].isna())]
    print("fund-quarters shown: %d | NAV/share changed vs published: %d | identity ok: %d | by fund changed: %s" % (
        len(report), len(changed), int(report["identity_ok"].sum()), changed["cik"].value_counts().to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
