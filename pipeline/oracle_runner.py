"""Oracle runner -- orchestrates all oracle checks and writes artifacts.

Usage:
    python -m pipeline.oracle_runner                  # All CIKs, all checks
    python -m pipeline.oracle_runner --cik 0001786108 # One CIK
    python -m pipeline.oracle_runner --checks A01,A04 # Specific checks
    python -m pipeline.oracle_runner --category A     # One category
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.bdc_xbrl_wrapper import normalize_cik
from pipeline.config import (
    BDC_HOLDINGS_FILE,
    FUND_FINANCIALS_FILE,
    OUTPUT_DIR,
    POSITION_MATCHES_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.oracle_checks import (
    ALL_CHECK_IDS,
    CATEGORIES,
    CHECK_REGISTRY,
    CheckResult,
    _col_str,
)

logger = logging.getLogger(__name__)

ORACLE_OUTPUT_DIR = OUTPUT_DIR / "oracle"

RESULTS_COLUMNS = [
    "check_id",
    "scope",
    "status",
    "metric_value",
    "threshold",
    "residual_rows",
    "residual_fv",
    "message",
    "cik",
    "report_date",
    "detail_rows",
]

FAILURE_DETAIL_COLUMNS = [
    "check_id",
    "cik",
    "report_date",
    "row_index",
    "detail_json",
]


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_holdings(cik: str | None = None) -> pd.DataFrame:
    """Load unified holdings, optionally filtered to one CIK."""
    if not UNIFIED_HOLDINGS_FILE.exists():
        logger.warning("Unified holdings file not found: %s", UNIFIED_HOLDINGS_FILE)
        return pd.DataFrame()
    df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
    if cik:
        cik_norm = normalize_cik(cik)
        df = df[_col_str(df, "cik").str.zfill(10).eq(cik_norm)].copy()
    return df


def _load_fund_financials(cik: str | None = None) -> pd.DataFrame | None:
    """Load fund financials, optionally filtered to one CIK."""
    if not FUND_FINANCIALS_FILE.exists():
        return None
    try:
        df = pd.read_csv(FUND_FINANCIALS_FILE, dtype=str)
        if cik:
            cik_norm = normalize_cik(cik)
            df = df[_col_str(df, "cik").str.zfill(10).eq(cik_norm)].copy()
        return df
    except Exception:
        return None


def _load_source_detail(cik: str | None = None) -> pd.DataFrame:
    """Load source reconciliation detail for the given CIK (or all).

    Tries per-CIK Parquet cache first, falls back to the combined CSV.
    """
    from pipeline.config import (
        BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE,
        SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR,
        SOURCE_RECONCILIATION_DETAIL_FILE,
    )

    if cik:
        cik_norm = normalize_cik(cik)
        per_cik = SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR / f"{cik_norm}.parquet"
        if per_cik.exists():
            try:
                return pd.read_parquet(per_cik)
            except Exception:
                pass

    if SOURCE_RECONCILIATION_DETAIL_FILE.exists():
        try:
            df = pd.read_csv(SOURCE_RECONCILIATION_DETAIL_FILE, dtype=str)
            if cik:
                cik_norm = normalize_cik(cik)
                df = df[_col_str(df, "cik").str.zfill(10).eq(cik_norm)].copy()
            return df
        except Exception:
            pass

    return pd.DataFrame()


def _load_matches(cik: str | None = None) -> pd.DataFrame | None:
    """Load position matches, optionally filtered to one CIK."""
    if not POSITION_MATCHES_FILE.exists():
        return None
    try:
        df = pd.read_csv(POSITION_MATCHES_FILE, dtype=str)
        if cik:
            cik_norm = normalize_cik(cik)
            df = df[_col_str(df, "cik").str.zfill(10).eq(cik_norm)].copy()
        return df
    except Exception:
        return None


# ---------------------------------------------------------------------------
# OracleReport
# ---------------------------------------------------------------------------

class OracleReport:
    """Container for oracle check results."""

    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def add(self, results: list[CheckResult]) -> None:
        self.results.extend(results)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == "pass")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "fail")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == "warn")

    @property
    def skip_count(self) -> int:
        return sum(1 for r in self.results if r.status == "skip")

    def summary_df(self) -> pd.DataFrame:
        rows = [r.to_dict() for r in self.results]
        if not rows:
            return pd.DataFrame(columns=RESULTS_COLUMNS)
        return pd.DataFrame(rows)[RESULTS_COLUMNS]

    def failure_detail_df(self) -> pd.DataFrame:
        """Concatenate all failure detail DataFrames with check_id prefix."""
        dfs = []
        for r in self.results:
            if r.status in ("fail", "warn") and not r.detail.empty:
                detail = r.detail.head(200).copy()
                detail.insert(0, "check_id", r.check_id)
                if "cik" not in detail.columns:
                    detail["cik"] = r.cik
                if "report_date" not in detail.columns:
                    detail["report_date"] = r.report_date
                dfs.append(detail)
        if not dfs:
            return pd.DataFrame()
        return pd.concat(dfs, ignore_index=True)

    def summary_text(self) -> str:
        """Human-readable oracle summary."""
        lines = [
            "# Oracle Check Results",
            "",
            f"Total checks: {self.total}",
            f"  Pass: {self.pass_count}",
            f"  Fail: {self.fail_count}",
            f"  Warn: {self.warn_count}",
            f"  Skip: {self.skip_count}",
            "",
        ]

        # Group by category
        by_cat: dict[str, list[CheckResult]] = {}
        for r in self.results:
            cat = r.check_id[0] if r.check_id else "?"
            by_cat.setdefault(cat, []).append(r)

        for cat_id in sorted(by_cat.keys()):
            cat_name = CATEGORIES.get(cat_id, "Unknown")
            cat_results = by_cat[cat_id]
            cat_pass = sum(1 for r in cat_results if r.status == "pass")
            cat_fail = sum(1 for r in cat_results if r.status == "fail")
            cat_warn = sum(1 for r in cat_results if r.status == "warn")
            cat_skip = sum(1 for r in cat_results if r.status == "skip")
            lines.append(f"## {cat_id}: {cat_name}")
            lines.append(
                f"  {len(cat_results)} checks: "
                f"{cat_pass} pass, {cat_fail} fail, "
                f"{cat_warn} warn, {cat_skip} skip"
            )

            for r in cat_results:
                icon = {"pass": "[PASS]", "fail": "[FAIL]", "warn": "[WARN]", "skip": "[SKIP]"}
                lines.append(f"  {icon.get(r.status, '[????]')} {r.check_id}: {r.message}")

            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_oracle(
    cik: str | None = None,
    checks: list[str] | None = None,
    category: str | None = None,
    output_dir: Path | None = None,
) -> OracleReport:
    """Run oracle checks and write artifacts.

    Args:
        cik: Filter to one CIK (None = all CIKs).
        checks: Specific check IDs to run (None = all).
        category: Run all checks in one category (e.g. "A").
        output_dir: Override output directory.
    """
    out_dir = output_dir or ORACLE_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine which checks to run
    check_ids = ALL_CHECK_IDS
    if checks:
        check_ids = [c.upper() for c in checks if c.upper() in CHECK_REGISTRY]
    elif category:
        cat = category.upper()
        check_ids = [c for c in ALL_CHECK_IDS if c.startswith(cat)]

    if not check_ids:
        logger.warning("No valid checks selected")
        return OracleReport()

    logger.info("Running %d oracle checks%s", len(check_ids),
                f" for CIK {cik}" if cik else " (all CIKs)")

    # Load data once
    holdings_df = _load_holdings(cik)
    fund_financials_df = _load_fund_financials(cik)
    source_detail_df = _load_source_detail(cik)
    matches_df = _load_matches(cik)

    logger.info("Loaded: holdings=%d rows, financials=%s, source_detail=%d rows, matches=%s",
                len(holdings_df),
                f"{len(fund_financials_df)} rows" if fund_financials_df is not None else "None",
                len(source_detail_df),
                f"{len(matches_df)} rows" if matches_df is not None else "None")

    report = OracleReport()

    for check_id in check_ids:
        if check_id not in CHECK_REGISTRY:
            continue
        func, inputs_desc = CHECK_REGISTRY[check_id]
        logger.info("Running %s ...", check_id)

        try:
            results = _dispatch_check(
                check_id, func, inputs_desc,
                holdings_df=holdings_df,
                fund_financials_df=fund_financials_df,
                source_detail_df=source_detail_df,
                matches_df=matches_df,
            )
            report.add(results)
        except Exception as e:
            logger.error("Check %s failed with error: %s", check_id, e)
            report.add([CheckResult(
                check_id=check_id,
                scope="global",
                status="skip",
                metric_value=0,
                threshold=0,
                residual_rows=0,
                residual_fv=0,
                message=f"Error: {e}",
                cik=cik or "",
            )])

    # Write artifacts
    _write_artifacts(report, out_dir, cik)

    return report


def _dispatch_check(
    check_id: str,
    func: Any,
    inputs_desc: str,
    *,
    holdings_df: pd.DataFrame,
    fund_financials_df: pd.DataFrame | None,
    source_detail_df: pd.DataFrame,
    matches_df: pd.DataFrame | None = None,
) -> list[CheckResult]:
    """Call the check function with the right arguments based on inputs_desc."""
    import inspect
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())

    kwargs: dict[str, Any] = {}

    for param in params:
        if param in ("holdings_df",):
            kwargs[param] = holdings_df
        elif param in ("fund_financials_df",):
            kwargs[param] = fund_financials_df
        elif param in ("source_detail_df", "source_detail"):
            kwargs[param] = source_detail_df
        elif param in ("matches_df",):
            kwargs[param] = matches_df
        # Skip keyword-only params with defaults

    # Filter kwargs to only include params that the function accepts
    valid_kwargs = {}
    for key, val in kwargs.items():
        if key in params:
            valid_kwargs[key] = val

    return func(**valid_kwargs)


def _write_artifacts(report: OracleReport, out_dir: Path, cik: str | None) -> None:
    """Write oracle output artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check results summary
    summary_df = report.summary_df()
    summary_df.to_csv(out_dir / "check_results.csv", index=False)

    # Failure details
    failures_df = report.failure_detail_df()
    if not failures_df.empty:
        failures_df.to_csv(out_dir / "check_failures.csv", index=False)

    # Human-readable report
    summary_text = report.summary_text()
    (out_dir / "oracle_summary.md").write_text(summary_text, encoding="utf-8")

    # Per-CIK breakdown
    if cik:
        cik_dir = out_dir / normalize_cik(cik)
        cik_dir.mkdir(parents=True, exist_ok=True)
        summary_df.to_csv(cik_dir / "check_results.csv", index=False)
        if not failures_df.empty:
            failures_df.to_csv(cik_dir / "check_failures.csv", index=False)
        (cik_dir / "oracle_summary.md").write_text(summary_text, encoding="utf-8")

    logger.info(
        "Oracle complete: %d checks (%d pass, %d fail, %d warn, %d skip). "
        "Artifacts in %s",
        report.total, report.pass_count, report.fail_count,
        report.warn_count, report.skip_count, out_dir,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run comprehensive BDC XBRL oracle checks."
    )
    parser.add_argument("--cik", default=None, help="Filter to one CIK")
    parser.add_argument("--checks", default=None,
                        help="Comma-separated check IDs (e.g. A01,A04,F01)")
    parser.add_argument("--category", default=None,
                        help="Run all checks in one category (e.g. A, B, F)")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--fail-on-failure", action="store_true",
                        help="Exit code 1 if any check fails")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    checks = args.checks.split(",") if args.checks else None

    report = run_oracle(
        cik=args.cik,
        checks=checks,
        category=args.category,
        output_dir=args.output_dir,
    )

    print(report.summary_text())

    if args.fail_on_failure and report.fail_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
