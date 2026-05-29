"""Export pre-computed JSON for the static Next.js frontend.

Reads pipeline output CSVs with DuckDB, writes aggregated JSON files to
``frontend/public/data/``.  No position-level data is exposed -- only
index-level time-series and aggregated summaries.

Usage:
    python -m pipeline.main --export-frontend
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from pipeline.config import (
    BDC_SECTOR_BREAKDOWN_FILE,
    BDC_SECTOR_BREAKDOWN_RECONCILED_FILE,
    BDC_SECTOR_RECONCILIATION_FILE,
    CLASSIFICATION_VALIDATION_FILE,
    COLUMN_QUALITY_METRICS_FILE,
    DATA_QUALITY_METRICS_FILE,
    CIK_TO_MANAGER_BRAND,
    FEE_UPLIFT_FILE,
    FUND_IDENTITY_FILE,
    HOLDINGS_GAV_RECONCILIATION_FILE,
    INDEX_DISPLAY_END_QUARTER,
    LLM_FUND_VALIDATION_RESULTS_FILE,
    OUTPUT_DIR,
    POSITION_PURITY_METRICS_FILE,
    PROJECT_ROOT,
    ROW_VALIDATION_ISSUES_FILE,
    VALIDATION_REPORT_FILE,
)
from pipeline.index_returns import MIN_BEGIN_FV

logger = logging.getLogger(__name__)

# Annualized risk-free rate assumption for Sharpe ratio calculation.
# Uses 4% as a rough average 3M T-Bill rate over the index history period
# (2019-2025).  Could be replaced with a quarterly series for more precision.
RISK_FREE_RATE_ANNUAL = 0.04

FRONTEND_DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"

# Consumer/marketplace lending CIKs -- these report individual consumer loans
# (~380K rows, <1% of total FV) that inflate counts without meaningful data.
CONSUMER_LENDING_EXCLUDE_CIKS = {"0001678130", "0001644771", "0002041175"}


def _exclude_consumer_lending_sql(cik_col: str = "cik") -> str:
    """SQL fragment to exclude consumer/marketplace lending CIKs."""
    ciks = ", ".join(f"'{c}'" for c in CONSUMER_LENDING_EXCLUDE_CIKS)
    return f" AND {cik_col} NOT IN ({ciks})"


# Source CSVs
INDEX_RETURNS_CSV = OUTPUT_DIR / "index_returns.csv"
POSITION_RETURNS_CSV = OUTPUT_DIR / "position_returns.csv"
UNIFIED_HOLDINGS_CSV = OUTPUT_DIR / "private_markets_holdings.csv"
COMBINED_UNIVERSE_CSV = OUTPUT_DIR / "combined_universe.csv"
FUND_FINANCIALS_CSV = OUTPUT_DIR / "fund_financials.csv"
FUND_IDENTITY_CSV = FUND_IDENTITY_FILE
BDC_FUND_INCOME_CSV = OUTPUT_DIR / "bdc_fund_income.csv"
NONACCRUAL_FLAGS_CSV = OUTPUT_DIR / "nonaccrual_flags.csv"

# Index display order
INDEX_ORDER = [
    "DIRECT_LENDING",
    "PREFERRED_EQUITY",
    "COMMON_EQUITY",
    "PRIVATE_CREDIT_FUND",
    "PRIVATE_EQUITY_FUND",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quarter_cutoff_sql(col: str = "quarter") -> str:
    """Return a SQL fragment ``AND col <= '...'`` if a display cutoff is set."""
    if INDEX_DISPLAY_END_QUARTER is None:
        return ""
    return f" AND {col} <= '{INDEX_DISPLAY_END_QUARTER}'"

def _write_bytes_retry(path: Path, payload: bytes, retries: int = 5) -> None:
    """Write bytes with atomic rename + retry for Windows file-locking."""
    tmp = path.with_suffix(".tmp")
    for attempt in range(retries):
        try:
            tmp.write_bytes(payload)
            tmp.replace(path)
            return
        except OSError:
            if attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
            else:
                raise


def _write_json(name: str, data: Any) -> Path:
    """Write *data* as compact JSON to ``FRONTEND_DATA_DIR / name``."""
    path = FRONTEND_DATA_DIR / name
    _write_bytes_retry(
        path,
        json.dumps(data, default=str, separators=(",", ":")).encode("utf-8"),
    )
    size_kb = path.stat().st_size / 1024
    logger.info("  Wrote %s (%.1f KB)", name, size_kb)
    return path


def _quarter_to_date(q: str) -> str:
    """Convert '2025q4' to '2025-12-31'."""
    year = int(q[:4])
    qn = int(q[5])
    month = qn * 3
    # Last day of quarter
    if month == 3:
        return f"{year}-03-31"
    if month == 6:
        return f"{year}-06-30"
    if month == 9:
        return f"{year}-09-30"
    return f"{year}-12-31"


def _prev_quarter(q: str) -> str:
    """Return the quarter label immediately before *q*.  '2020q1' -> '2019q4'."""
    year = int(q[:4])
    qn = int(q[5])
    if qn == 1:
        return f"{year - 1}q4"
    return f"{year}q{qn - 1}"


def _safe_round(val: Any, digits: int = 4) -> Any:
    """Round floats, pass through None/str."""
    if val is None:
        return None
    try:
        return round(float(val), digits)
    except (ValueError, TypeError):
        return val


# Standard 1.0-centred histogram bucket edges & labels
_STD_EDGES = [0.3, 0.5, 0.65, 0.8, 0.9, 0.95, 0.98, 1.02, 1.05, 1.1, 1.2, 1.5, 2.0]
_STD_LABELS = [
    "<0.3", "0.3-0.5", "0.5-0.65", "0.65-0.8", "0.8-0.9",
    "0.9-0.95", "0.95-0.98", "0.98-1.02", "1.02-1.05",
    "1.05-1.1", "1.1-1.2", "1.2-1.5", "1.5-2.0", ">2.0",
]


def _build_recon_hist(
    values: list[float],
    metric_id: str,
    title: str,
    subtitle: str,
    edges: list[float] | None = None,
    labels: list[str] | None = None,
    center: float = 1.0,
) -> dict[str, Any] | None:
    """Bucket *values* into a histogram dict for the frontend."""
    if not values:
        return None
    if edges is None:
        edges = _STD_EDGES
    if labels is None:
        labels = _STD_LABELS
    n = len(values)
    vs = sorted(values)
    med = vs[n // 2]
    counts = [0] * len(labels)
    for v in values:
        placed = False
        for i, edge in enumerate(edges):
            if v < edge:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    return {
        "id": metric_id,
        "title": title,
        "subtitle": subtitle,
        "n": n,
        "median": round(med, 3),
        "centerValue": center,
        "histogram": [
            {"bucket": labels[i], "count": counts[i]} for i in range(len(labels))
        ],
    }


def _valid_positions_sql() -> str:
    """SQL CTEs ``latest`` and ``valid`` for deduplicated index positions.

    Applies the same filters as the index calculation:
    - quarterly_total_return IS NOT NULL
    - begin_fair_value >= MIN_BEGIN_FV ($100K)
    - Deduplicated: one row per (index_classification, cik, issuer_name)
      keeping the row with the highest end_fair_value.
    """
    return f"""latest AS (
            SELECT index_classification, MAX(end_quarter) AS q
            FROM read_csv_auto('{POSITION_RETURNS_CSV.as_posix()}')
            WHERE index_classification IS NOT NULL
              {_quarter_cutoff_sql('end_quarter')}
            GROUP BY index_classification
        ),
        valid AS (
            SELECT * FROM (
                SELECT pr.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY pr.index_classification, pr.cik, pr.issuer_name
                        ORDER BY
                            pr.end_fair_value DESC NULLS LAST,
                            pr.end_cost DESC NULLS LAST,
                            pr.end_quarter DESC NULLS LAST,
                            pr.asset_category ASC NULLS LAST,
                            pr.entity_name ASC NULLS LAST,
                            pr.cik ASC NULLS LAST,
                            pr.issuer_name ASC NULLS LAST
                    ) AS _dedup_rn
                FROM read_csv_auto('{POSITION_RETURNS_CSV.as_posix()}') pr
                JOIN latest l
                  ON pr.index_classification = l.index_classification
                 AND pr.end_quarter = l.q
                WHERE pr.quarterly_total_return IS NOT NULL
                  AND pr.begin_fair_value >= {MIN_BEGIN_FV}
                  {_exclude_consumer_lending_sql('pr.cik')}
            )
            WHERE _dedup_rn = 1
        )"""


# ---------------------------------------------------------------------------
# Export functions
# ---------------------------------------------------------------------------


__all__ = [
    name
    for name in globals()
    if not name.startswith("__") and name not in {"annotations"}
]
