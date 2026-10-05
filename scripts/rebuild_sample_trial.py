"""Trial unified build for a small set of funds, and a row-level comparison of two trials.

The inner loop for fixing extraction gaps on the working sample: build the
sample funds into a trial folder in minutes, then compare with the previous
trial (or with production) to see exactly which rows and fund-quarter totals a
change moved. It is NOT a production rebuild and publishes nothing.

What it covers: the unified stage (staging, wrappers, classification, promoted
corrections, financial preparation) for the chosen funds, starting from the
already-extracted bdc_holdings / nport_holdings. A change to the raw XBRL
extraction needs those inputs re-extracted first.

What it cannot show: effects on funds outside the set, and anything computed
across funds (entity matching, sector labels). Those columns are compared but
reported separately as cross-fund changes. A shared-code change still needs a
full rebuild and `diff_outputs.py --semantic` before it is published.

Default funds: `findings_scope.ciks` in the quarter acceptance thresholds.

Usage (from the repo root; no network; not while a full rebuild is running):
    python scripts/rebuild_sample_trial.py --label before
    python scripts/rebuild_sample_trial.py --label after --compare-to before
    python scripts/rebuild_sample_trial.py --label check --compare-to production
    python scripts/rebuild_sample_trial.py --compare before after     # no build
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TRIAL_ROOT = ROOT / "scratch" / "trial_builds"
HOLDINGS_NAME = "private_markets_holdings.csv"
KEY = "row_id"
# Computed across all funds in a build, so a subset build legitimately differs.
CROSS_FUND_COLUMNS = ("entity_id", "canonical_name", "gics_sub_industry", "gics_sector")
UNDERLYING = "underlying_schedule"
PAD = "lpad(regexp_replace(cast(cik AS VARCHAR),'[^0-9]','','g'),10,'0')"

logger = logging.getLogger("sample_trial")


def default_ciks() -> list[str]:
    """The acceptance contract's findings scope (the working sample)."""
    from pipeline import config
    spec = json.loads(config.QUARTER_ACCEPTANCE_THRESHOLDS_FILE.read_text(encoding="utf-8-sig"))
    return sorted(str(c).zfill(10) for c in (spec.get("findings_scope") or {}).get("ciks") or [])


def _text(frame: pd.DataFrame) -> pd.DataFrame:
    """All cells as comparable text: missing -> '', numeric text by value."""
    out = {}
    for column in frame.columns:
        values = frame[column].astype(object).where(frame[column].notna(), "").astype(str)
        numeric = pd.to_numeric(values, errors="coerce").astype(float)   # '100' == '100.0'
        out[column] = values.where(numeric.isna(), numeric.map(repr))
    return pd.DataFrame(out, index=frame.index)


def fund_quarter_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows and published-basis sums per fund-quarter (JV underlying rows excluded)."""
    work = pd.DataFrame({
        "cik": frame["cik"].astype(str).str.zfill(10),
        "report_date": frame["report_date"].astype(str).str[:10],
        "fair_value": pd.to_numeric(frame["fair_value"], errors="coerce").fillna(0.0),
        "cost": pd.to_numeric(frame.get("cost"), errors="coerce").fillna(0.0)
        if "cost" in frame else 0.0,
        "published": (frame["accounting_record_class"].astype(str) != UNDERLYING)
        if "accounting_record_class" in frame else True,
    })
    work["rows"] = 1
    for name in ("fair_value", "cost"):
        work[name] = work[name].where(work["published"], 0.0)
    work["published_rows"] = work["published"].astype(int)
    return (work.groupby(["cik", "report_date"], as_index=False)
            [["rows", "published_rows", "fair_value", "cost"]].sum())


def compare_runs(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """Row-level difference of two builds keyed on row_id; row order is ignored."""
    for name, frame in (("before", before), ("after", after)):
        if frame[KEY].duplicated().any():
            raise ValueError(f"{name} run repeats {KEY}; cannot compare row by row")
    a, b = before.set_index(KEY), after.set_index(KEY)
    common = a.index.intersection(b.index)
    shared = [c for c in a.columns if c in b.columns]
    left, right = _text(a.loc[common, shared]), _text(b.loc[common, shared])
    differs = left.ne(right)
    cross = [c for c in shared if c in CROSS_FUND_COLUMNS]
    own = [c for c in shared if c not in CROSS_FUND_COLUMNS]
    changed_by_column = {c: int(differs[c].sum()) for c in own if differs[c].any()}
    cross_changes = {c: int(differs[c].sum()) for c in cross if differs[c].any()}
    rows_changed = int(differs[own].any(axis=1).sum()) if own else 0

    totals = fund_quarter_summary(before).merge(
        fund_quarter_summary(after), on=["cik", "report_date"], how="outer",
        suffixes=("_before", "_after")).fillna(0.0)
    fund_quarters = []
    for row in totals.sort_values(["cik", "report_date"]).to_dict("records"):
        delta = row["fair_value_after"] - row["fair_value_before"]
        row_delta = int(row["rows_after"] - row["rows_before"])
        if delta or row_delta:
            fund_quarters.append(dict(
                cik=row["cik"], report_date=row["report_date"],
                rows_before=int(row["rows_before"]), rows_after=int(row["rows_after"]),
                fair_value_before=row["fair_value_before"], fair_value_after=row["fair_value_after"],
                fair_value_delta=delta))
    added = sorted(b.index.difference(a.index))
    removed = sorted(a.index.difference(b.index))
    return dict(
        rows_before=len(a), rows_after=len(b), rows_added=added, rows_removed=removed,
        rows_changed=rows_changed, changed_by_column=changed_by_column,
        cross_fund_changes=cross_changes, fund_quarters=fund_quarters,
        columns_only_before=[c for c in a.columns if c not in b.columns],
        columns_only_after=[c for c in b.columns if c not in a.columns],
        identical=not (added or removed or rows_changed or cross_changes))


def print_report(report: dict, before_label: str, after_label: str) -> None:
    print("compare %s -> %s" % (before_label, after_label))
    print("  rows %d -> %d | added %d | removed %d | changed %d" % (
        report["rows_before"], report["rows_after"], len(report["rows_added"]),
        len(report["rows_removed"]), report["rows_changed"]))
    for title, key in (("changed columns", "changed_by_column"),
                       ("cross-fund columns (expected to differ in a subset)", "cross_fund_changes")):
        if report[key]:
            print("  %s:" % title)
            for column, n in sorted(report[key].items(), key=lambda kv: -kv[1]):
                print("    %-34s %d rows" % (column, n))
    if report["fund_quarters"]:
        print("  fund-quarters whose rows or published fair value moved: %d" % len(report["fund_quarters"]))
        for fq in report["fund_quarters"][:40]:
            print("    %s %s rows %d -> %d  fair value %.0f -> %.0f (%+.0f)" % (
                fq["cik"], fq["report_date"], fq["rows_before"], fq["rows_after"],
                fq["fair_value_before"], fq["fair_value_after"], fq["fair_value_delta"]))
    for key in ("columns_only_before", "columns_only_after"):
        if report[key]:
            print("  %s: %s" % (key, report[key]))
    print("  RESULT: %s" % ("IDENTICAL" if report["identical"] else "DIFFERENT"))


def _load_subset(path: Path, ciks: list[str]) -> pd.DataFrame:
    import duckdb
    with duckdb.connect(config={"threads": 2}) as con:
        con.execute("CREATE TEMP TABLE subset AS SELECT unnest(?) AS cik", [ciks])
        frame = con.execute(
            f"SELECT * FROM read_parquet(?) WHERE {PAD} IN (SELECT cik FROM subset)",
            [str(path)]).fetchdf()
    # Production stages the parquet inside DuckDB, where DATE casts to 'YYYY-MM-DD'.
    # A pandas datetime64 column would cast to 'YYYY-MM-DD 00:00:00' and silently
    # break period filters and row selectors (changelog 2026-10-04).
    for column in frame.columns:
        if str(frame[column].dtype).startswith("datetime64"):
            frame[column] = frame[column].dt.strftime("%Y-%m-%d")
    return frame


def _load_run(label: str, ciks: list[str]) -> pd.DataFrame:
    """A trial run's holdings, or the published holdings for the same funds."""
    if label == "production":
        from pipeline import config
        import duckdb
        with duckdb.connect(config={"threads": 2}) as con:
            con.execute("CREATE TEMP TABLE subset AS SELECT unnest(?) AS cik", [ciks])
            return con.execute(
                f"SELECT * FROM read_csv(?, header=true, all_varchar=true) "
                f"WHERE {PAD} IN (SELECT cik FROM subset)",
                [str(config.OUTPUT_DIR / HOLDINGS_NAME)]).fetchdf()
    path = TRIAL_ROOT / label / HOLDINGS_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no trial run named {label!r}: {path}")
    return pd.read_csv(path, dtype=str)


def _protected_state(directory: Path) -> dict:
    return {p.name: (p.stat().st_mtime_ns, p.stat().st_size)
            for p in directory.iterdir() if p.is_file()}


def build(label: str, ciks: list[str], finalize: bool = False) -> Path:
    """Build the funds into scratch. finalize=True runs the whole build (entity resolution,
    financial preparation, position matching, identities); False stops after staging."""
    from unittest.mock import patch

    from pipeline import config
    from pipeline.unified_holdings import build_unified_holdings

    run_dir = TRIAL_ROOT / label
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    before = _protected_state(config.OUTPUT_DIR)
    t0 = time.time()
    bdc = _load_subset(config.BDC_HOLDINGS_PARQUET_FILE, ciks)
    nport = (_load_subset(config.NPORT_HOLDINGS_PARQUET_FILE, ciks)
             if config.NPORT_HOLDINGS_PARQUET_FILE.exists() else pd.DataFrame())
    logger.info("sample: %d funds, %d raw bdc rows, %d raw nport rows", len(ciks), len(bdc), len(nport))
    # The build may append to the GICS label cache; give it a private copy.
    label_cache = run_dir / "gics_label_cache.csv"
    if config.GICS_LABEL_CACHE_FILE.exists():
        shutil.copy2(config.GICS_LABEL_CACHE_FILE, label_cache)
    with patch("pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", label_cache):
        if finalize:
            from pipeline.holdings_finalizer import build_final_holdings
            frame, _ = build_final_holdings(bdc_df=bdc, nport_df=nport, output_file=run_dir / HOLDINGS_NAME)
        else:
            frame = build_unified_holdings(
                bdc_df=bdc, nport_df=nport, output_file=run_dir / HOLDINGS_NAME,
                orphan_file=run_dir / "universe_orphan_holdings.csv")
    fund_quarter_summary(frame).to_csv(run_dir / "fund_quarter_summary.csv", index=False)
    head = ""
    try:
        import subprocess
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        pass
    (run_dir / "run.json").write_text(json.dumps(dict(
        label=label, ciks=ciks, rows=len(frame), finalized=finalize, seconds=round(time.time() - t0, 1),
        git_head=head, built=time.strftime("%Y-%m-%d %H:%M:%S")), indent=2), encoding="utf-8")
    after = _protected_state(config.OUTPUT_DIR)
    touched = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
    if touched:
        raise RuntimeError("trial build changed production files: " + ", ".join(touched))
    logger.info("trial %s: %d rows in %.0f s -> %s", label, len(frame), time.time() - t0, run_dir)
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", help="name of the trial run to build (overwrites a run of that name)")
    parser.add_argument("--ciks", nargs="*", default=None,
                        help="funds to build; default = acceptance findings scope")
    parser.add_argument("--compare-to", default=None,
                        help="after building, compare with this earlier run, or 'production'")
    parser.add_argument("--finalize", action="store_true",
                        help="also run entity resolution, matching and identities (untested here; "
                             "prefer scripts/fund_ledger_trial.py for an end-to-end fund build)")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                        help="compare two existing runs without building")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    ciks = sorted({"".join(ch for ch in c if ch.isdigit()).zfill(10) for c in args.ciks}) \
        if args.ciks else default_ciks()
    if not ciks:
        parser.error("no funds: pass --ciks or set findings_scope in the acceptance thresholds")
    if args.compare:
        before_label, after_label = args.compare
    elif args.label:
        build(args.label, ciks, finalize=args.finalize)
        if not args.compare_to:
            return 0
        before_label, after_label = args.compare_to, args.label
    else:
        parser.error("give --label to build or --compare BEFORE AFTER")
    report = compare_runs(_load_run(before_label, ciks), _load_run(after_label, ciks))
    print_report(report, before_label, after_label)
    out = TRIAL_ROOT / after_label / f"compare_to_{before_label}.json"
    if out.parent.is_dir():
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
