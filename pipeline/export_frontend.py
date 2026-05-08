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
    CLASSIFICATION_VALIDATION_FILE,
    CIK_TO_MANAGER_BRAND,
    FEE_UPLIFT_FILE,
    FUND_IDENTITY_FILE,
    HOLDINGS_GAV_RECONCILIATION_FILE,
    INDEX_DISPLAY_END_QUARTER,
    LLM_FUND_VALIDATION_RESULTS_FILE,
    OUTPUT_DIR,
    PROJECT_ROOT,
    VALIDATION_REPORT_FILE,
)
from pipeline.index_returns import MIN_BEGIN_FV

logger = logging.getLogger(__name__)

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
                        ORDER BY pr.end_fair_value DESC NULLS LAST
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

def _export_index_returns(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Export full index time-series.  Returns the raw rows for reuse."""
    if not INDEX_RETURNS_CSV.exists():
        logger.warning("index_returns.csv not found -- writing empty JSON")
        _write_json("index_returns.json", {})
        return []

    rows = con.execute(f"""
        SELECT index_classification, quarter,
               fv_weighted_return, equal_weighted_return,
               cost_weighted_return,
               constituent_count, total_begin_fv, total_end_fv,
               index_level_fv, index_level_equal, index_level_cost
        FROM read_csv_auto('{INDEX_RETURNS_CSV.as_posix()}')
        WHERE 1=1 {_quarter_cutoff_sql('quarter')}
        ORDER BY index_classification, quarter
    """).fetchall()

    cols = [
        "index_classification", "quarter",
        "fv_weighted_return", "equal_weighted_return",
        "cost_weighted_return",
        "constituent_count", "total_begin_fv", "total_end_fv",
        "index_level_fv", "index_level_equal", "index_level_cost",
    ]
    raw = [dict(zip(cols, r)) for r in rows]

    # Group by index
    out: dict[str, list[dict]] = {}
    for row in raw:
        idx = row["index_classification"]
        out.setdefault(idx, []).append({
            "quarter": row["quarter"],
            "fvReturn": _safe_round(row["fv_weighted_return"], 6),
            "eqReturn": _safe_round(row["equal_weighted_return"], 6),
            "costReturn": _safe_round(row["cost_weighted_return"], 6),
            "constituents": row["constituent_count"],
            "totalBeginFv": _safe_round(row["total_begin_fv"], 0),
            "totalEndFv": _safe_round(row["total_end_fv"], 0),
            "levelFv": _safe_round(row["index_level_fv"], 2),
            "levelEqual": _safe_round(row["index_level_equal"], 2),
            "levelCost": _safe_round(row["index_level_cost"], 2),
        })

    # Prepend a synthetic baseline point (level=100) one quarter before
    # each index's first real data so charts visually start at 100.
    for idx, series in out.items():
        if series:
            first_q = series[0]["quarter"]
            series.insert(0, {
                "quarter": _prev_quarter(first_q),
                "fvReturn": 0.0,
                "eqReturn": 0.0,
                "costReturn": 0.0,
                "constituents": 0,
                "totalBeginFv": 0,
                "totalEndFv": 0,
                "levelFv": 100.0,
                "levelEqual": 100.0,
                "levelCost": 100.0,
            })

    _write_json("index_returns.json", out)
    return raw


def _export_index_summary(
    raw_returns: list[dict],
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Compute summary stats per index from the index_returns data."""
    if not raw_returns:
        _write_json("index_summary.json", [])
        return

    # Count unique companies and unique positions per index (latest quarter).
    # position_returns has one row per match pair -- the same end-period
    # position can appear in multiple pairs (different span lengths), so we
    # deduplicate to unique (cik, issuer_name) before counting.
    unique_companies: dict[str, int] = {}
    unique_positions: dict[str, int] = {}
    if POSITION_RETURNS_CSV.exists():
        uc_rows = con.execute(f"""
            WITH latest AS (
                SELECT index_classification, MAX(end_quarter) AS q
                FROM read_csv_auto('{POSITION_RETURNS_CSV.as_posix()}')
                WHERE index_classification IS NOT NULL
                  {_quarter_cutoff_sql('end_quarter')}
                GROUP BY index_classification
            ),
            deduped AS (
                SELECT DISTINCT pr.index_classification, pr.cik, pr.issuer_name
                FROM read_csv_auto('{POSITION_RETURNS_CSV.as_posix()}') pr
                JOIN latest l
                  ON pr.index_classification = l.index_classification
                 AND pr.end_quarter = l.q
                WHERE pr.quarterly_total_return IS NOT NULL
                  AND pr.begin_fair_value >= {MIN_BEGIN_FV}
            )
            SELECT index_classification,
                   COUNT(DISTINCT issuer_name) AS n_companies,
                   COUNT(*) AS n_positions
            FROM deduped
            GROUP BY index_classification
        """).fetchall()
        for idx_name, n_co, n_pos in uc_rows:
            unique_companies[idx_name] = n_co
            unique_positions[idx_name] = n_pos

    # Group by index
    by_idx: dict[str, list[dict]] = {}
    for r in raw_returns:
        by_idx.setdefault(r["index_classification"], []).append(r)

    summaries = []
    for idx in INDEX_ORDER:
        series = by_idx.get(idx, [])
        if not series:
            continue
        # Sort by quarter
        series.sort(key=lambda x: x["quarter"])
        latest = series[-1]
        level = latest["index_level_fv"]
        level_eq = latest["index_level_equal"]

        # QoQ return
        qoq = latest["fv_weighted_return"]

        # Trailing 12M (last 4 quarters compounded)
        last4 = series[-4:] if len(series) >= 4 else series
        trail_12m = 1.0
        for s in last4:
            r = s["fv_weighted_return"]
            if r is not None:
                trail_12m *= (1 + r)
        trail_12m -= 1

        # YTD: quarters in same year as latest
        latest_year = latest["quarter"][:4]
        ytd_quarters = [s for s in series if s["quarter"][:4] == latest_year]
        ytd = 1.0
        for s in ytd_quarters:
            r = s["fv_weighted_return"]
            if r is not None:
                ytd *= (1 + r)
        ytd -= 1

        # Annualized since inception
        n_quarters = len(series)
        if n_quarters > 0 and level is not None and level > 0:
            total_return = level / 100.0 - 1
            years = n_quarters / 4
            if years > 0:
                annualized = (1 + total_return) ** (1 / years) - 1
            else:
                annualized = 0
        else:
            annualized = 0

        # Sparkline: last 8 quarter levels
        spark = [
            _safe_round(s["index_level_fv"], 2)
            for s in series[-8:]
            if s["index_level_fv"] is not None
        ]

        summaries.append({
            "index": idx,
            "level": _safe_round(level, 2),
            "levelEqual": _safe_round(level_eq, 2),
            "qoqReturn": _safe_round(qoq, 6),
            "trailing12m": _safe_round(trail_12m, 6),
            "ytd": _safe_round(ytd, 6),
            "annualized": _safe_round(annualized, 6),
            "constituents": unique_positions.get(idx, latest["constituent_count"]),
            "uniqueCompanies": unique_companies.get(idx, 0),
            "totalFv": _safe_round(latest["total_end_fv"], 0),
            "latestQuarter": latest["quarter"],
            "sparkline": spark,
        })

    _write_json("index_summary.json", summaries)


def _export_top_constituents(con: duckdb.DuckDBPyConnection) -> None:
    """Top 20 positions per index by end_fair_value (latest quarter)."""
    if not POSITION_RETURNS_CSV.exists():
        _write_json("top_constituents.json", {})
        return

    rows = con.execute(f"""
        WITH {_valid_positions_sql()},
        ranked AS (
            SELECT
                pr.index_classification,
                pr.issuer_name,
                pr.asset_category,
                pr.end_fair_value,
                pr.end_cost,
                CASE WHEN pr.end_cost > 0
                     THEN (pr.end_fair_value - pr.end_cost) / pr.end_cost * 100
                END AS unrealized_gl_pct,
                pr.cik,
                pr.entity_name,
                pr.quarterly_total_return AS total_return,
                CASE WHEN TRY_CAST(pr.begin_basis_spread AS DOUBLE) > 0 THEN 'Floating'
                     WHEN TRY_CAST(pr.begin_interest_rate AS DOUBLE) > 0 THEN 'Fixed'
                END AS rate_type,
                ROW_NUMBER() OVER (
                    PARTITION BY pr.index_classification
                    ORDER BY pr.end_fair_value DESC NULLS LAST
                ) AS rn
            FROM valid pr
        )
        SELECT * FROM ranked WHERE rn <= 20
    """).fetchall()

    cols = [
        "index_classification", "issuer_name", "asset_category",
        "end_fair_value", "end_cost", "unrealized_gl_pct",
        "cik", "entity_name", "total_return", "rate_type", "rn",
    ]

    out: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(zip(cols, row))
        idx = d["index_classification"]
        out.setdefault(idx, []).append({
            "issuerName": d["issuer_name"],
            "assetCategory": d["asset_category"],
            "fairValue": _safe_round(d["end_fair_value"], 0),
            "cost": _safe_round(d["end_cost"], 0),
            "unrealizedGlPct": _safe_round(d["unrealized_gl_pct"], 2),
            "vehicleName": d["entity_name"],
            "totalReturn": _safe_round(d["total_return"], 6),
            "rateType": d["rate_type"],
        })

    _write_json("top_constituents.json", out)


def _export_sector_breakdown(con: duckdb.DuckDBPyConnection) -> None:
    """Asset category breakdown per index (latest quarter)."""
    if not POSITION_RETURNS_CSV.exists():
        _write_json("sector_breakdown.json", {})
        return

    rows = con.execute(f"""
        WITH {_valid_positions_sql()},
        agg AS (
            SELECT
                pr.index_classification,
                COALESCE(pr.asset_category, 'OTHER') AS asset_category,
                COUNT(*) AS position_count,
                SUM(pr.end_fair_value) AS total_fv
            FROM valid pr
            GROUP BY pr.index_classification, COALESCE(pr.asset_category, 'OTHER')
        )
        SELECT
            index_classification,
            asset_category,
            position_count,
            total_fv,
            total_fv / SUM(total_fv) OVER (
                PARTITION BY index_classification
            ) AS pct_of_index
        FROM agg
        ORDER BY index_classification, total_fv DESC
    """).fetchall()

    cols = ["index_classification", "asset_category", "position_count",
            "total_fv", "pct_of_index"]

    out: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(zip(cols, row))
        idx = d["index_classification"]
        out.setdefault(idx, []).append({
            "assetCategory": d["asset_category"],
            "positionCount": d["position_count"],
            "totalFv": _safe_round(d["total_fv"], 0),
            "pctOfIndex": _safe_round(d["pct_of_index"], 4),
        })

    _write_json("sector_breakdown.json", out)


def _export_vehicle_contribution(con: duckdb.DuckDBPyConnection) -> None:
    """Per-vehicle (entity) breakdown per index (latest quarter)."""
    if not POSITION_RETURNS_CSV.exists() or not COMBINED_UNIVERSE_CSV.exists():
        _write_json("vehicle_contribution.json", {})
        return

    rows = con.execute(f"""
        WITH {_valid_positions_sql()},
        agg AS (
            SELECT
                pr.index_classification,
                pr.cik,
                pr.entity_name,
                COUNT(*) AS position_count,
                SUM(pr.end_fair_value) AS total_fv
            FROM valid pr
            GROUP BY pr.index_classification, pr.cik, pr.entity_name
        ),
        univ AS (
            SELECT cik, vehicle_type,
                   ROW_NUMBER() OVER (PARTITION BY cik ORDER BY cik) AS rn
            FROM read_csv_auto('{COMBINED_UNIVERSE_CSV.as_posix()}')
        ),
        univ_dedup AS (
            SELECT cik, vehicle_type FROM univ WHERE rn = 1
        )
        SELECT
            a.index_classification,
            a.cik,
            a.entity_name,
            COALESCE(u.vehicle_type, 'unknown') AS vehicle_type,
            a.position_count,
            a.total_fv,
            a.total_fv / NULLIF(SUM(a.total_fv) OVER (
                PARTITION BY a.index_classification
            ), 0) AS pct_of_index
        FROM agg a
        LEFT JOIN univ_dedup u
          ON CAST(TRY_CAST(a.cik AS BIGINT) AS VARCHAR)
           = CAST(TRY_CAST(u.cik AS BIGINT) AS VARCHAR)
        ORDER BY a.index_classification, a.total_fv DESC
    """).fetchall()

    cols = ["index_classification", "cik", "entity_name", "vehicle_type",
            "position_count", "total_fv", "pct_of_index"]

    out: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(zip(cols, row))
        idx = d["index_classification"]
        out.setdefault(idx, []).append({
            "cik": d["cik"],
            "entityName": d["entity_name"],
            "vehicleType": d["vehicle_type"],
            "positionCount": d["position_count"],
            "totalFv": _safe_round(d["total_fv"], 0),
            "pctOfIndex": _safe_round(d["pct_of_index"], 4),
        })

    _write_json("vehicle_contribution.json", out)


def _export_portfolio_characteristics(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """DL-specific portfolio stats (WAC, WAS, WAM, lien/rate splits)."""
    if not UNIFIED_HOLDINGS_CSV.exists():
        _write_json("portfolio_characteristics.json", {})
        return

    # Latest quarter for DL holdings
    # Use all_varchar=true then CAST to avoid type inference errors
    # (some rows have "True" in numeric columns)
    stats = con.execute(f"""
        WITH raw AS (
            SELECT * FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
        ),
        dl AS (
            SELECT
                CAST(fair_value AS DOUBLE) AS fair_value,
                TRY_CAST(interest_rate AS DOUBLE) AS interest_rate,
                TRY_CAST(basis_spread AS DOUBLE) AS basis_spread,
                maturity_date,
                asset_category,
                coupon_type,
                issuer_name,
                report_date
            FROM raw
            WHERE index_classification = 'DIRECT_LENDING'
              AND TRY_CAST(fair_value AS DOUBLE) > 0
        ),
        cutoff AS (
            SELECT CASE WHEN '{INDEX_DISPLAY_END_QUARTER}' = 'None' THEN NULL
                        ELSE '{_quarter_to_date(INDEX_DISPLAY_END_QUARTER) if INDEX_DISPLAY_END_QUARTER else "9999-12-31"}'
                   END AS max_date
        ),
        latest_q AS (
            SELECT MAX(report_date) AS q FROM dl
            WHERE report_date <= (SELECT COALESCE(max_date, '9999-12-31') FROM cutoff)
        ),
        cur AS (
            SELECT * FROM dl
            WHERE report_date = (SELECT q FROM latest_q)
        )
        SELECT
            (SELECT q FROM latest_q) AS as_of,
            COUNT(*) AS position_count,
            SUM(fair_value) AS total_fv,

            -- WAC (weighted avg coupon)
            SUM(CASE WHEN interest_rate IS NOT NULL AND interest_rate > 0
                     THEN interest_rate * fair_value END)
            / NULLIF(SUM(CASE WHEN interest_rate IS NOT NULL AND interest_rate > 0
                              THEN fair_value END), 0)
            AS wac,

            -- WAS (weighted avg spread)
            SUM(CASE WHEN basis_spread IS NOT NULL AND basis_spread > 0
                     THEN basis_spread * fair_value END)
            / NULLIF(SUM(CASE WHEN basis_spread IS NOT NULL AND basis_spread > 0
                              THEN fair_value END), 0)
            AS was,

            -- WAM (weighted avg maturity in years)
            SUM(CASE WHEN maturity_date IS NOT NULL
                          AND TRY_CAST(maturity_date AS DATE) IS NOT NULL
                     THEN (TRY_CAST(maturity_date AS DATE)
                           - CURRENT_DATE)::INTEGER / 365.25 * fair_value
                END)
            / NULLIF(SUM(CASE WHEN maturity_date IS NOT NULL
                                   AND TRY_CAST(maturity_date AS DATE) IS NOT NULL
                              THEN fair_value END), 0)
            AS wam,

            -- Lien split by FV (parse lien position from issuer_name text)
            SUM(CASE WHEN LOWER(issuer_name) LIKE '%second lien%'
                       OR LOWER(issuer_name) LIKE '%2nd lien%'
                       OR LOWER(issuer_name) LIKE '%junior lien%'
                       OR LOWER(issuer_name) LIKE '%junior secured%'
                     THEN fair_value ELSE 0 END) AS second_lien_fv,
            SUM(CASE WHEN LOWER(issuer_name) LIKE '%unsecured%'
                       OR LOWER(issuer_name) LIKE '%subordinat%'
                       OR LOWER(issuer_name) LIKE '%mezzanine%'
                     THEN fair_value ELSE 0 END) AS unsecured_fv,

            -- Rate type split
            SUM(CASE WHEN LOWER(coupon_type) IN ('floating', 'variable')
                     THEN fair_value ELSE 0 END) AS floating_fv,
            SUM(CASE WHEN LOWER(coupon_type) = 'fixed'
                     THEN fair_value ELSE 0 END) AS fixed_fv,

            -- Coverage counts
            COUNT(CASE WHEN interest_rate IS NOT NULL AND interest_rate > 0
                       THEN 1 END) AS wac_count,
            COUNT(CASE WHEN basis_spread IS NOT NULL AND basis_spread > 0
                       THEN 1 END) AS was_count,
            COUNT(CASE WHEN maturity_date IS NOT NULL
                         AND TRY_CAST(maturity_date AS DATE) IS NOT NULL
                       THEN 1 END) AS wam_count
        FROM cur
    """).fetchone()

    if stats is None or stats[0] is None:
        _write_json("portfolio_characteristics.json", {})
        return

    (as_of, pos_count, total_fv,
     wac, was, wam,
     second_lien_fv, unsecured_fv,
     floating_fv, fixed_fv,
     wac_count, was_count, wam_count) = stats

    total_fv_f = float(total_fv or 0)
    # First lien = everything not classified as second lien or unsecured
    first_lien_fv = total_fv_f - float(second_lien_fv or 0) - float(unsecured_fv or 0)

    def _pct(val: Any) -> Any:
        v = float(val or 0)
        if total_fv_f == 0:
            return 0
        return _safe_round(v / total_fv_f, 4)

    _write_json("portfolio_characteristics.json", {
        "asOf": as_of,
        "positionCount": pos_count,
        "totalFv": _safe_round(total_fv_f, 0),
        "wac": _safe_round(wac, 2),
        "was": _safe_round(was, 2),
        "wam": _safe_round(wam, 1),
        "wacCoverage": _safe_round(wac_count / pos_count, 4) if pos_count else 0,
        "wasCoverage": _safe_round(was_count / pos_count, 4) if pos_count else 0,
        "wamCoverage": _safe_round(wam_count / pos_count, 4) if pos_count else 0,
        "lienSplit": {
            "firstLien": _pct(first_lien_fv),
            "secondLien": _pct(second_lien_fv),
            "unsecured": _pct(unsecured_fv),
        },
        "rateTypeSplit": {
            "floating": _pct(floating_fv),
            "fixed": _pct(fixed_fv),
        },
    })


def _export_metadata(
    con: duckdb.DuckDBPyConnection,
    raw_returns: list[dict],
) -> None:
    """As-of date, total AUM, vehicle counts, data vintage."""
    # Latest quarter from returns, or from holdings
    latest_quarter = None
    if raw_returns:
        latest_quarter = max(r["quarter"] for r in raw_returns)

    if latest_quarter is None and UNIFIED_HOLDINGS_CSV.exists():
        cutoff_date = _quarter_to_date(INDEX_DISPLAY_END_QUARTER) if INDEX_DISPLAY_END_QUARTER else '9999-12-31'
        result = con.execute(f"""
            SELECT MAX(report_date) FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
            WHERE report_date <= '{cutoff_date}'
        """).fetchone()
        if result and result[0]:
            # Convert date to quarter format
            rd = str(result[0])
            try:
                yr = int(rd[:4])
                mo = int(rd[5:7])
                qn = (mo - 1) // 3 + 1
                latest_quarter = f"{yr}q{qn}"
            except (ValueError, IndexError):
                pass

    # Vehicle counts from universe
    vehicle_counts = {"bdc": 0, "interval_fund": 0, "tender_offer_fund": 0}
    total_vehicles = 0
    if COMBINED_UNIVERSE_CSV.exists():
        vc_rows = con.execute(f"""
            SELECT vehicle_type, COUNT(*) AS n
            FROM read_csv_auto('{COMBINED_UNIVERSE_CSV.as_posix()}')
            GROUP BY vehicle_type
        """).fetchall()
        for vt, n in vc_rows:
            vehicle_counts[str(vt)] = n
            total_vehicles += n

    # Total AUM from holdings (latest quarter)
    total_aum = 0
    holdings_count = 0
    cik_count = 0
    issuer_count = 0
    if UNIFIED_HOLDINGS_CSV.exists():
        cutoff_date = _quarter_to_date(INDEX_DISPLAY_END_QUARTER) if INDEX_DISPLAY_END_QUARTER else '9999-12-31'
        aum_row = con.execute(f"""
            WITH raw AS (
                SELECT * FROM read_csv_auto(
                    '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
                )
            ),
            latest AS (
                SELECT MAX(report_date) AS q FROM raw
                WHERE report_date <= '{cutoff_date}'
            )
            SELECT
                SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
                COUNT(*) AS n_holdings,
                COUNT(DISTINCT cik) AS n_ciks
            FROM raw
            WHERE report_date = (SELECT q FROM latest)
        """).fetchone()
        if aum_row:
            total_aum = float(aum_row[0] or 0)
            holdings_count = aum_row[1] or 0
            cik_count = aum_row[2] or 0

    # Unique issuers among index constituents (position_returns with begin_fv >= 100K)
    if POSITION_RETURNS_CSV.exists():
        ir_row = con.execute(f"""
            WITH pr AS (
                SELECT * FROM read_csv_auto(
                    '{POSITION_RETURNS_CSV.as_posix()}', all_varchar=true
                )
                WHERE index_classification IS NOT NULL
                  AND index_classification != 'UNCLASSIFIED'
                  AND TRY_CAST(begin_fair_value AS DOUBLE) >= 100000
                  {_quarter_cutoff_sql('end_quarter')}
            ),
            latest AS (SELECT MAX(end_quarter) AS q FROM pr)
            SELECT COUNT(DISTINCT issuer_name)
            FROM pr
            WHERE end_quarter = (SELECT q FROM latest)
        """).fetchone()
        if ir_row:
            issuer_count = ir_row[0] or 0

    _write_json("metadata.json", {
        "asOfQuarter": latest_quarter,
        "asOfDate": _quarter_to_date(latest_quarter) if latest_quarter else None,
        "totalAum": _safe_round(total_aum, 0),
        "vehicleCount": total_vehicles,
        "bdcCount": vehicle_counts.get("bdc", 0),
        "intervalFundCount": vehicle_counts.get("interval_fund", 0),
        "tenderOfferCount": vehicle_counts.get("tender_offer_fund", 0),
        "holdingsCount": holdings_count,
        "cikCount": cik_count,
        "uniqueIssuers": issuer_count,
        "dataVintage": datetime.now(timezone.utc).isoformat(),
    })


def _top_n_with_other(
    rows: list[dict],
    *,
    name_key: str,
    n: int = 10,
    extra_keys: list[str] | None = None,
) -> list[dict]:
    """Keep top *n* entries by ``rn``, lump the rest into "Other".

    Each row dict must have ``rn``, ``total_fv``, ``pct_of_index``,
    ``position_count``, and the field named by *name_key*.
    *extra_keys* are summed into the Other bucket as ints.
    """
    extra = extra_keys or []
    top: list[dict] = []
    other_fv = 0.0
    other_pos = 0
    other_extra = {k: 0 for k in extra}
    total_fv = sum(float(r["total_fv"] or 0) for r in rows)

    for r in rows:
        if r["rn"] <= n:
            entry: dict = {
                "name": r[name_key],
                "totalFv": _safe_round(r["total_fv"], 0),
                "pctOfIndex": _safe_round(r["pct_of_index"], 4),
                "positionCount": int(r["position_count"] or 0),
            }
            for k in extra:
                entry[k] = int(r.get(k) or 0)
            top.append(entry)
        else:
            other_fv += float(r["total_fv"] or 0)
            other_pos += int(r["position_count"] or 0)
            for k in extra:
                other_extra[k] += int(r.get(k) or 0)

    if other_fv > 0:
        entry = {
            "name": "Other",
            "totalFv": _safe_round(other_fv, 0),
            "pctOfIndex": _safe_round(other_fv / total_fv if total_fv else 0, 4),
            "positionCount": other_pos,
        }
        for k in extra:
            entry[k] = other_extra[k]
        top.append(entry)

    return top


def _export_manager_concentration(con: duckdb.DuckDBPyConnection) -> None:
    """Manager (brand) concentration per index, latest quarter."""
    if not POSITION_RETURNS_CSV.exists():
        _write_json("manager_concentration.json", {})
        return

    brand_values = ", ".join(
        f"('{cik}', '{brand}')" for cik, brand in CIK_TO_MANAGER_BRAND.items()
    )

    rows = con.execute(f"""
        WITH {_valid_positions_sql()},
        brand_map(cik_mapped, brand) AS (
            VALUES {brand_values}
        ),
        per_cik AS (
            SELECT
                pr.index_classification,
                pr.cik,
                pr.entity_name,
                COUNT(*) AS position_count,
                SUM(pr.end_fair_value) AS total_fv
            FROM valid pr
            GROUP BY pr.index_classification, pr.cik, pr.entity_name
        ),
        branded AS (
            SELECT
                pc.index_classification,
                COALESCE(bm.brand, pc.entity_name) AS manager,
                pc.position_count,
                pc.total_fv,
                pc.cik
            FROM per_cik pc
            LEFT JOIN brand_map bm
              ON CAST(TRY_CAST(pc.cik AS BIGINT) AS VARCHAR)
               = CAST(TRY_CAST(bm.cik_mapped AS BIGINT) AS VARCHAR)
        ),
        by_manager AS (
            SELECT
                index_classification,
                manager,
                SUM(total_fv) AS total_fv,
                SUM(position_count) AS position_count,
                COUNT(DISTINCT cik) AS fund_count
            FROM branded
            GROUP BY index_classification, manager
        ),
        with_pct AS (
            SELECT *,
                total_fv / NULLIF(SUM(total_fv) OVER (
                    PARTITION BY index_classification
                ), 0) AS pct_of_index,
                ROW_NUMBER() OVER (
                    PARTITION BY index_classification
                    ORDER BY total_fv DESC
                ) AS rn
            FROM by_manager
        )
        SELECT index_classification, manager, total_fv, pct_of_index,
               position_count, fund_count, rn
        FROM with_pct
        ORDER BY index_classification, rn
    """).fetchall()

    cols = ["index_classification", "manager", "total_fv", "pct_of_index",
            "position_count", "fund_count", "rn"]

    by_idx: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(zip(cols, row))
        by_idx.setdefault(d["index_classification"], []).append(d)

    out: dict[str, list[dict]] = {}
    for idx, mgrs in by_idx.items():
        out[idx] = _top_n_with_other(
            mgrs, name_key="manager", extra_keys=["fund_count"],
        )

    _write_json("manager_concentration.json", out)


def _export_vehicle_concentration(con: duckdb.DuckDBPyConnection) -> None:
    """Per-fund concentration per index, latest quarter (top 10 + Other)."""
    if not POSITION_RETURNS_CSV.exists():
        _write_json("vehicle_concentration.json", {})
        return

    rows = con.execute(f"""
        WITH {_valid_positions_sql()},
        agg AS (
            SELECT
                pr.index_classification,
                pr.entity_name,
                COUNT(*) AS position_count,
                SUM(pr.end_fair_value) AS total_fv
            FROM valid pr
            GROUP BY pr.index_classification, pr.entity_name
        ),
        with_pct AS (
            SELECT *,
                total_fv / NULLIF(SUM(total_fv) OVER (
                    PARTITION BY index_classification
                ), 0) AS pct_of_index,
                ROW_NUMBER() OVER (
                    PARTITION BY index_classification
                    ORDER BY total_fv DESC
                ) AS rn
            FROM agg
        )
        SELECT index_classification, entity_name, total_fv, pct_of_index,
               position_count, rn
        FROM with_pct
        ORDER BY index_classification, rn
    """).fetchall()

    cols = ["index_classification", "entity_name", "total_fv", "pct_of_index",
            "position_count", "rn"]

    by_idx: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(zip(cols, row))
        by_idx.setdefault(d["index_classification"], []).append(d)

    out: dict[str, list[dict]] = {}
    for idx, vehicles in by_idx.items():
        out[idx] = _top_n_with_other(vehicles, name_key="entity_name")

    _write_json("vehicle_concentration.json", out)


def _export_investee_concentration(con: duckdb.DuckDBPyConnection) -> None:
    """Top investees (borrowers/companies) per index, latest quarter."""
    if not POSITION_RETURNS_CSV.exists():
        _write_json("investee_concentration.json", {})
        return

    rows = con.execute(f"""
        WITH {_valid_positions_sql()},
        agg AS (
            SELECT
                pr.index_classification,
                pr.issuer_name,
                COUNT(*) AS position_count,
                SUM(pr.end_fair_value) AS total_fv,
                COUNT(DISTINCT pr.cik) AS fund_count
            FROM valid pr
            GROUP BY pr.index_classification, pr.issuer_name
        ),
        with_pct AS (
            SELECT *,
                total_fv / NULLIF(SUM(total_fv) OVER (
                    PARTITION BY index_classification
                ), 0) AS pct_of_index,
                ROW_NUMBER() OVER (
                    PARTITION BY index_classification
                    ORDER BY total_fv DESC
                ) AS rn
            FROM agg
        )
        SELECT index_classification, issuer_name, total_fv, pct_of_index,
               position_count, fund_count, rn
        FROM with_pct
        ORDER BY index_classification, rn
    """).fetchall()

    cols = ["index_classification", "issuer_name", "total_fv", "pct_of_index",
            "position_count", "fund_count", "rn"]

    by_idx: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(zip(cols, row))
        by_idx.setdefault(d["index_classification"], []).append(d)

    out: dict[str, list[dict]] = {}
    for idx, investees in by_idx.items():
        out[idx] = _top_n_with_other(
            investees, name_key="issuer_name", extra_keys=["fund_count"],
        )

    _write_json("investee_concentration.json", out)


def _compute_brackets(
    ranked_rows: list[tuple],
    thresholds: list[int],
) -> list[dict]:
    """Compute incremental FV brackets from ranked (rn, total_count, grand_total, cum_fv) rows.

    Returns pie-chart-ready slices: "Top 1%", "Top 1-5%", ..., "Bottom 50%".
    Each slice has the *incremental* FV share (not cumulative).
    """
    total_count = ranked_rows[0][1]
    grand_total = float(ranked_rows[0][2])
    if grand_total <= 0:
        return []

    # Compute cumulative FV at each threshold
    cum_at: dict[int, float] = {}
    for pct in thresholds:
        cutoff_rank = max(1, int(total_count * pct / 100))
        if cutoff_rank <= len(ranked_rows):
            cum_at[pct] = float(ranked_rows[cutoff_rank - 1][3])
        else:
            cum_at[pct] = grand_total

    # Build incremental slices
    brackets = []
    prev_cum = 0.0
    prev_pct = 0
    for pct in thresholds:
        incr = cum_at[pct] - prev_cum
        lo = prev_pct
        hi = pct
        label = f"Top {hi}%" if lo == 0 else f"Top {lo}-{hi}%"
        count_lo = max(1, int(total_count * lo / 100)) if lo > 0 else 0
        count_hi = max(1, int(total_count * hi / 100))
        brackets.append({
            "label": label,
            "fvPct": _safe_round(incr / grand_total, 6),
            "count": count_hi - count_lo,
            "totalCount": total_count,
        })
        prev_cum = cum_at[pct]
        prev_pct = pct

    return brackets


def _ranked_query(
    con: duckdb.DuckDBPyConnection,
    *,
    group_col: str,
    where_clause: str = "",
) -> list[tuple]:
    """Query position_returns for ranked entities with cumulative FV.

    Uses the same positions that feed the index: deduplicated position_returns
    for the latest quarter (one row per position, FV > 0).
    """
    rows = con.execute(f"""
        WITH {_valid_positions_sql()},
        cur AS (
            SELECT * FROM valid
            WHERE end_fair_value > 0
              {where_clause}
        ),
        agg AS (
            SELECT
                {group_col} AS entity,
                SUM(end_fair_value) AS total_fv
            FROM cur
            GROUP BY {group_col}
        ),
        ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (ORDER BY total_fv DESC) AS rn,
                COUNT(*) OVER () AS total_count,
                SUM(total_fv) OVER () AS grand_total,
                SUM(total_fv) OVER (
                    ORDER BY total_fv DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS cum_fv
            FROM agg
        )
        SELECT rn, total_count, grand_total, cum_fv
        FROM ranked
        ORDER BY rn
    """).fetchall()
    return rows


def _export_concentration_curve(con: duckdb.DuckDBPyConnection) -> None:
    """Pie-chart-ready concentration brackets from position_returns.

    Uses the same positions as the indices (deduplicated position_returns
    for the latest quarter, FV > 0).  Two views: by company (issuer_name)
    and by position (issuer_name + cik).
    """
    if not POSITION_RETURNS_CSV.exists():
        _write_json("concentration_curve.json", {})
        return

    thresholds = [1, 5, 10, 20, 50, 100]
    out: dict[str, dict] = {}

    # Per-index + combined DL+DE
    index_filters = [
        ("DIRECT_LENDING", "AND index_classification = 'DIRECT_LENDING'"),
        ("PREFERRED_EQUITY", "AND index_classification = 'PREFERRED_EQUITY'"),
        ("COMMON_EQUITY", "AND index_classification = 'COMMON_EQUITY'"),
        ("PRIVATE_CREDIT_FUND", "AND index_classification = 'PRIVATE_CREDIT_FUND'"),
        ("PRIVATE_EQUITY_FUND", "AND index_classification = 'PRIVATE_EQUITY_FUND'"),
        ("COMBINED", "AND index_classification IN ('DIRECT_LENDING', 'PREFERRED_EQUITY', 'COMMON_EQUITY')"),
    ]

    for idx_key, where in index_filters:
        entry: dict[str, list[dict]] = {}

        # By company (issuer_name across all funds)
        rows = _ranked_query(
            con, group_col="issuer_name", where_clause=where,
        )
        if rows:
            entry["investee"] = _compute_brackets(rows, thresholds)

        # By position (issuer_name within a single fund)
        rows = _ranked_query(
            con,
            group_col="issuer_name || '|' || cik",
            where_clause=where,
        )
        if rows:
            entry["position"] = _compute_brackets(rows, thresholds)

        if entry:
            out[idx_key] = entry

    _write_json("concentration_curve.json", out)


def _export_position_concentration(con: duckdb.DuckDBPyConnection) -> None:
    """Top individual positions per index, latest quarter (no company grouping)."""
    if not POSITION_RETURNS_CSV.exists():
        _write_json("position_concentration.json", {})
        return

    rows = con.execute(f"""
        WITH {_valid_positions_sql()},
        positions AS (
            SELECT
                pr.index_classification,
                pr.issuer_name || ' (' || pr.entity_name || ')' AS position_label,
                pr.end_fair_value AS total_fv,
                1 AS position_count
            FROM valid pr
        ),
        with_pct AS (
            SELECT *,
                total_fv / NULLIF(SUM(total_fv) OVER (
                    PARTITION BY index_classification
                ), 0) AS pct_of_index,
                ROW_NUMBER() OVER (
                    PARTITION BY index_classification
                    ORDER BY total_fv DESC
                ) AS rn
            FROM positions
        )
        SELECT index_classification, position_label, total_fv, pct_of_index,
               position_count, rn
        FROM with_pct
        ORDER BY index_classification, rn
    """).fetchall()

    cols = ["index_classification", "position_label", "total_fv", "pct_of_index",
            "position_count", "rn"]

    by_idx: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(zip(cols, row))
        by_idx.setdefault(d["index_classification"], []).append(d)

    out: dict[str, list[dict]] = {}
    for idx, positions in by_idx.items():
        out[idx] = _top_n_with_other(positions, name_key="position_label")

    _write_json("position_concentration.json", out)


# ---------------------------------------------------------------------------
# Fund-level exports for one-pager pages
# ---------------------------------------------------------------------------

def _export_fund_list(con: duckdb.DuckDBPyConnection) -> None:
    """Export fund_list.json -- universe with latest-quarter snapshot."""
    if not FUND_FINANCIALS_CSV.exists():
        logger.warning("fund_financials.csv not found -- skipping fund_list")
        _write_json("fund_list.json", [])
        return

    # Optionally join identity data (adviser, ticker)
    has_identity = FUND_IDENTITY_CSV.exists()
    identity_join = ""
    identity_cols = (
        "CAST(NULL AS VARCHAR) AS adviser,"
        " CAST(NULL AS VARCHAR) AS ticker"
    )
    if has_identity:
        identity_join = f"""
        LEFT JOIN read_csv_auto('{FUND_IDENTITY_CSV.as_posix()}',
                                all_varchar=true) id
            ON CAST(TRY_CAST(f.cik AS BIGINT) AS VARCHAR)
             = CAST(TRY_CAST(id.cik AS BIGINT) AS VARCHAR)
        """
        identity_cols = (
            "COALESCE(id.adviser_name, '') AS adviser,"
            " COALESCE(id.ticker, '') AS ticker"
        )

    rows = con.execute(f"""
        WITH ff AS (
            SELECT * FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
        ),
        latest AS (
            SELECT cik, MAX(report_quarter) AS q
            FROM ff
            GROUP BY cik
            HAVING MAX(TRY_CAST(total_assets AS DOUBLE)) > 1000000
               AND MAX(report_quarter) >= '2022q4'
        ),
        snap AS (
            SELECT f.*
            FROM ff f
            JOIN latest l ON f.cik = l.cik AND f.report_quarter = l.q
        )
        SELECT
            f.cik,
            COALESCE(f.entity_name, '') AS name,
            COALESCE(f.vehicle_type, '') AS vehicle_type,
            {identity_cols},
            TRY_CAST(f.total_assets AS DOUBLE) AS total_assets,
            TRY_CAST(f.nav_per_share AS DOUBLE) AS nav_per_share,
            TRY_CAST(f.distribution_rate AS DOUBLE) AS distribution_rate,
            TRY_CAST(f.leverage_ratio AS DOUBLE) AS leverage_ratio,
            TRY_CAST(f.quarterly_return AS DOUBLE) AS quarterly_return,
            TRY_CAST(f.expense_ratio_pct AS DOUBLE) AS expense_ratio_pct,
            TRY_CAST(f.redemption_pressure AS DOUBLE) AS redemption_pressure,
            TRY_CAST(f.total_return_pct AS DOUBLE) AS total_return_pct,
            TRY_CAST(f.income_yield_pct AS DOUBLE) AS income_yield_pct,
            TRY_CAST(f.premium_discount_pct AS DOUBLE) AS premium_discount_pct,
            (SELECT COUNT(DISTINCT report_quarter) FROM ff
             WHERE cik = f.cik AND report_quarter >= '2022q4') AS quarters_of_data
        FROM snap f
        {identity_join}
        ORDER BY TRY_CAST(f.total_assets AS DOUBLE) DESC NULLS LAST
    """).fetchall()

    cols = [
        "cik", "name", "vehicle_type", "adviser", "ticker",
        "total_assets", "nav_per_share", "distribution_rate",
        "leverage_ratio", "quarterly_return", "expense_ratio_pct",
        "redemption_pressure", "total_return_pct", "income_yield_pct",
        "premium_discount_pct", "quarters_of_data",
    ]
    out = []
    for row in rows:
        d = dict(zip(cols, row))
        out.append({
            "cik": d["cik"],
            "name": d["name"],
            "vehicleType": d["vehicle_type"],
            "adviser": d["adviser"],
            "ticker": d["ticker"],
            "totalAssets": _safe_round(d["total_assets"], 0),
            "navPerShare": _safe_round(d["nav_per_share"], 2),
            "distributionRate": _safe_round(d["distribution_rate"], 2),
            "leverageRatio": _safe_round(d["leverage_ratio"], 4),
            "quarterlyReturn": _safe_round(d["quarterly_return"], 4),
            "expenseRatioPct": _safe_round(d["expense_ratio_pct"], 2),
            "redemptionPressure": _safe_round(d["redemption_pressure"], 2),
            "totalReturnPct": _safe_round(d["total_return_pct"], 4),
            "incomeYieldPct": _safe_round(d["income_yield_pct"], 4),
            "premiumDiscountPct": _safe_round(d["premium_discount_pct"], 2),
            "quartersOfData": d["quarters_of_data"],
        })

    _write_json("fund_list.json", out)


def _compute_fund_exposure(
    con: duckdb.DuckDBPyConnection,
    cik: str,
) -> dict | None:
    """Compute portfolio exposure breakdown for a single CIK's latest quarter."""
    row = con.execute(f"""
        WITH cur AS (
            SELECT *,
                CASE WHEN maturity_date IS NOT NULL
                          AND TRY_CAST(maturity_date AS DATE) IS NOT NULL
                          AND TRY_CAST(maturity_date AS DATE) > TRY_CAST(report_date AS DATE)
                          AND TRY_CAST(maturity_date AS DATE) < TRY_CAST(report_date AS DATE) + INTERVAL 30 YEAR
                     THEN (TRY_CAST(maturity_date AS DATE)
                           - TRY_CAST(report_date AS DATE))::INTEGER / 365.25
                END AS ytm
            FROM _holdings_latest
            WHERE cik = '{cik}'
        ),
        total AS (
            SELECT SUM(fair_value) AS total_fv FROM cur WHERE fair_value > 0
        )
        SELECT
            (SELECT total_fv FROM total) AS total_fv,
            -- Asset type split (expanded 11 index_classification values)
            SUM(CASE WHEN index_classification = 'DIRECT_LENDING'
                     THEN fair_value ELSE 0 END) AS debt_fv,
            SUM(CASE WHEN index_classification IN (
                    'PREFERRED_EQUITY', 'COMMON_EQUITY', 'DIRECT_REAL_ESTATE')
                     THEN fair_value ELSE 0 END) AS equity_fv,
            SUM(CASE WHEN index_classification IN (
                    'PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND',
                    'REAL_ESTATE_FUND', 'HEDGE_FUND')
                     THEN fair_value ELSE 0 END) AS fund_fv,
            SUM(CASE WHEN index_classification = 'STRUCTURED_CREDIT'
                     THEN fair_value ELSE 0 END) AS structured_fv,
            SUM(CASE WHEN index_classification = 'CASH'
                     THEN fair_value ELSE 0 END) AS cash_fv,
            SUM(CASE WHEN index_classification = 'UNCLASSIFIED'
                          OR index_classification IS NULL
                     THEN fair_value ELSE 0 END) AS other_fv,
            -- Asset class split (7 values from asset_class column)
            SUM(CASE WHEN asset_class = 'PRIVATE_CREDIT' THEN fair_value ELSE 0 END) AS ac_private_credit,
            SUM(CASE WHEN asset_class = 'PRIVATE_EQUITY' THEN fair_value ELSE 0 END) AS ac_private_equity,
            SUM(CASE WHEN asset_class = 'REAL_ESTATE' THEN fair_value ELSE 0 END) AS ac_real_estate,
            SUM(CASE WHEN asset_class = 'STRUCTURED_CREDIT' THEN fair_value ELSE 0 END) AS ac_structured_credit,
            SUM(CASE WHEN asset_class = 'HEDGE_FUND' THEN fair_value ELSE 0 END) AS ac_hedge_fund,
            SUM(CASE WHEN asset_class = 'CASH' THEN fair_value ELSE 0 END) AS ac_cash,
            SUM(CASE WHEN asset_class = 'OTHER' OR asset_class IS NULL THEN fair_value ELSE 0 END) AS ac_other,
            -- Exposure type split (3 values)
            SUM(CASE WHEN exposure_type = 'DIRECT' THEN fair_value ELSE 0 END) AS et_direct,
            SUM(CASE WHEN exposure_type = 'FUND' THEN fair_value ELSE 0 END) AS et_fund,
            SUM(CASE WHEN exposure_type = 'LIQUID' THEN fair_value ELSE 0 END) AS et_liquid,
            -- Lien position (debt only)
            SUM(CASE WHEN index_classification = 'DIRECT_LENDING'
                      AND (LOWER(issuer_name) LIKE '%second lien%'
                           OR LOWER(issuer_name) LIKE '%2nd lien%'
                           OR LOWER(issuer_name) LIKE '%junior lien%'
                           OR LOWER(issuer_name) LIKE '%junior secured%')
                     THEN fair_value ELSE 0 END) AS second_lien_fv,
            SUM(CASE WHEN index_classification = 'DIRECT_LENDING'
                      AND (LOWER(issuer_name) LIKE '%unsecured%'
                           OR LOWER(issuer_name) LIKE '%subordinat%'
                           OR LOWER(issuer_name) LIKE '%mezzanine%')
                     THEN fair_value ELSE 0 END) AS unsecured_fv,
            -- Lien coverage: FV of positions with ANY explicit lien keyword
            SUM(CASE WHEN index_classification = 'DIRECT_LENDING'
                      AND (LOWER(issuer_name) LIKE '%first lien%'
                           OR LOWER(issuer_name) LIKE '%1st lien%'
                           OR LOWER(issuer_name) LIKE '%senior secured%'
                           OR LOWER(issuer_name) LIKE '%second lien%'
                           OR LOWER(issuer_name) LIKE '%2nd lien%'
                           OR LOWER(issuer_name) LIKE '%junior lien%'
                           OR LOWER(issuer_name) LIKE '%junior secured%'
                           OR LOWER(issuer_name) LIKE '%unsecured%'
                           OR LOWER(issuer_name) LIKE '%subordinat%'
                           OR LOWER(issuer_name) LIKE '%mezzanine%'
                           OR LOWER(issuer_name) LIKE '%unitranche%')
                     THEN fair_value ELSE 0 END) AS lien_identified_fv,
            -- Rate type (debt only)
            SUM(CASE WHEN index_classification = 'DIRECT_LENDING'
                      AND LOWER(coupon_type) IN ('floating', 'variable')
                     THEN fair_value ELSE 0 END) AS floating_fv,
            SUM(CASE WHEN index_classification = 'DIRECT_LENDING'
                      AND LOWER(coupon_type) = 'fixed'
                     THEN fair_value ELSE 0 END) AS fixed_fv,
            -- WAC / WAS (all positions with rate data)
            SUM(CASE WHEN interest_rate > 0 THEN interest_rate * fair_value END)
                / NULLIF(SUM(CASE WHEN interest_rate > 0 THEN fair_value END), 0) AS wac,
            SUM(CASE WHEN basis_spread > 0 THEN basis_spread * fair_value END)
                / NULLIF(SUM(CASE WHEN basis_spread > 0 THEN fair_value END), 0) AS was,
            -- WAC coverage: % of direct private credit FV with rate data
            SUM(CASE WHEN asset_class = 'PRIVATE_CREDIT' AND exposure_type = 'DIRECT'
                      AND interest_rate > 0 THEN fair_value ELSE 0 END) AS wac_pc_fv,
            SUM(CASE WHEN asset_class = 'PRIVATE_CREDIT' AND exposure_type = 'DIRECT'
                     THEN fair_value ELSE 0 END) AS pc_direct_fv,
            -- WAM (weighted avg maturity in years)
            SUM(CASE WHEN ytm IS NOT NULL THEN ytm * fair_value END)
                / NULLIF(SUM(CASE WHEN ytm IS NOT NULL THEN fair_value END), 0) AS wam,
            SUM(CASE WHEN ytm IS NOT NULL THEN fair_value ELSE 0 END) AS wam_fv,
            -- Maturity buckets (per-year: <1, 1-2, 2-3, 3-4, 4-5, 5-6, 6-7, 7+)
            SUM(CASE WHEN ytm >= 0 AND ytm < 1 THEN fair_value ELSE 0 END) AS mat_0,
            SUM(CASE WHEN ytm >= 1 AND ytm < 2 THEN fair_value ELSE 0 END) AS mat_1,
            SUM(CASE WHEN ytm >= 2 AND ytm < 3 THEN fair_value ELSE 0 END) AS mat_2,
            SUM(CASE WHEN ytm >= 3 AND ytm < 4 THEN fair_value ELSE 0 END) AS mat_3,
            SUM(CASE WHEN ytm >= 4 AND ytm < 5 THEN fair_value ELSE 0 END) AS mat_4,
            SUM(CASE WHEN ytm >= 5 AND ytm < 6 THEN fair_value ELSE 0 END) AS mat_5,
            SUM(CASE WHEN ytm >= 6 AND ytm < 7 THEN fair_value ELSE 0 END) AS mat_6,
            SUM(CASE WHEN ytm >= 7 THEN fair_value ELSE 0 END) AS mat_7p,
            -- Unrealized G/L
            SUM(fair_value) AS sum_fv,
            SUM(cost) AS sum_cost,
            SUM(CASE WHEN cost > 0 THEN cost END) AS total_cost_nonnull,
            SUM(CASE WHEN cost > 0 AND fair_value < cost THEN fair_value ELSE 0 END) AS underwater_fv,
            COUNT(CASE WHEN cost > 0 AND fair_value < cost THEN 1 END) AS underwater_count,
            COUNT(CASE WHEN cost > 0 THEN 1 END) AS has_cost_count,
            -- PIK exposure
            SUM(CASE WHEN index_classification = 'DIRECT_LENDING'
                      AND TRY_CAST(pik_rate AS DOUBLE) > 0
                     THEN fair_value ELSE 0 END) AS pik_bdc_fv,
            SUM(CASE WHEN LOWER(TRIM(nport_is_paid_in_kind)) = 'y'
                     THEN fair_value ELSE 0 END) AS pik_nport_fv,
            -- Fair value hierarchy (N-PORT only)
            SUM(CASE WHEN fair_value_level = '1' THEN fair_value ELSE 0 END) AS fvl_1,
            SUM(CASE WHEN fair_value_level = '2' THEN fair_value ELSE 0 END) AS fvl_2,
            SUM(CASE WHEN fair_value_level = '3' THEN fair_value ELSE 0 END) AS fvl_3,
            SUM(CASE WHEN fair_value_level IS NOT NULL AND TRIM(fair_value_level) != ''
                     THEN fair_value ELSE 0 END) AS fvl_total,
            -- Credit flags (N-PORT only)
            SUM(CASE WHEN LOWER(TRIM(nport_is_default)) = 'y'
                     THEN fair_value ELSE 0 END) AS default_fv,
            SUM(CASE WHEN LOWER(TRIM(nport_are_interest_payments_in_arrears)) = 'y'
                     THEN fair_value ELSE 0 END) AS arrears_fv,
            COUNT(CASE WHEN nport_is_default IS NOT NULL AND TRIM(nport_is_default) != ''
                       THEN 1 END) AS credit_flag_count,
            -- Position count
            COUNT(*) AS position_count
        FROM cur
        WHERE fair_value IS NOT NULL
    """).fetchone()

    if row is None or row[0] is None or float(row[0] or 0) <= 0:
        return None

    (total_fv, debt_fv, equity_fv, fund_fv, structured_fv, cash_fv, other_fv,
     ac_private_credit, ac_private_equity, ac_real_estate, ac_structured_credit,
     ac_hedge_fund, ac_cash, ac_other,
     et_direct, et_fund_exp, et_liquid,
     second_lien_fv, unsecured_fv, lien_identified_fv,
     floating_fv, fixed_fv,
     wac, was,
     wac_pc_fv, pc_direct_fv,
     wam, wam_fv,
     mat_0, mat_1, mat_2, mat_3, mat_4, mat_5, mat_6, mat_7p,
     sum_fv, sum_cost, total_cost_nonnull, underwater_fv, underwater_count, has_cost_count,
     pik_bdc_fv, pik_nport_fv,
     fvl_1, fvl_2, fvl_3, fvl_total,
     default_fv, arrears_fv, credit_flag_count,
     position_count) = row

    total_fv_f = float(total_fv or 0)
    debt_fv_f = float(debt_fv or 0)
    position_count_i = int(position_count or 0)

    def _pct(v: float) -> float | None:
        if total_fv_f <= 0:
            return None
        return round(v / total_fv_f, 4)

    first_lien_fv = debt_fv_f - float(second_lien_fv or 0) - float(unsecured_fv or 0)
    lien_coverage = (
        round(float(lien_identified_fv or 0) / debt_fv_f, 4)
        if debt_fv_f > 0 else None
    )

    # WAC coverage (% of direct private credit FV with rate data)
    pc_direct_fv_f = float(pc_direct_fv or 0)
    wac_pc_fv_f = float(wac_pc_fv or 0)
    wac_coverage = (
        round(wac_pc_fv_f / pc_direct_fv_f, 4)
        if pc_direct_fv_f > 0 else None
    )

    # WAM coverage
    wam_fv_f = float(wam_fv or 0)
    wam_cov = round(wam_fv_f / total_fv_f, 4) if total_fv_f > 0 else None

    # Maturity bucket percentages (per-year, over FV with maturity data)
    mat_vals = [float(v or 0) for v in [mat_0, mat_1, mat_2, mat_3, mat_4, mat_5, mat_6, mat_7p]]
    mat_total = sum(mat_vals)
    def _mat_pct(v: Any) -> float:
        if mat_total <= 0:
            return 0
        return round(float(v or 0) / mat_total, 4)

    # Unrealized G/L
    total_cost_nn = float(total_cost_nonnull or 0)
    unrealized_agg_pct = (
        round((float(sum_fv or 0) - total_cost_nn) / total_cost_nn, 4)
        if total_cost_nn > 0 else None
    )
    pct_underwater = (
        round(float(underwater_fv or 0) / total_fv_f, 4)
        if total_fv_f > 0 else None
    )
    cost_coverage = (
        round(float(has_cost_count or 0) / position_count_i, 4)
        if position_count_i > 0 else None
    )

    # Top 10 concentration (separate query)
    top10_pct = None
    top10_row = con.execute(f"""
        WITH ranked AS (
            SELECT fair_value,
                   ROW_NUMBER() OVER (ORDER BY fair_value DESC) AS rn
            FROM _holdings_latest
            WHERE cik = '{cik}' AND fair_value > 0
        ),
        total AS (SELECT SUM(fair_value) AS t FROM ranked)
        SELECT SUM(fair_value) / (SELECT t FROM total)
        FROM ranked WHERE rn <= 10
    """).fetchone()
    if top10_row and top10_row[0] is not None:
        top10_pct = _safe_round(top10_row[0], 4)

    # PIK exposure
    pik_bdc_f = float(pik_bdc_fv or 0)
    pik_nport_f = float(pik_nport_fv or 0)
    pik_fv = max(pik_bdc_f, pik_nport_f)
    pik_pct = round(pik_fv / debt_fv_f, 4) if debt_fv_f > 0 and pik_fv > 0 else None
    pik_label = "Paying in Kind" if pik_nport_f > pik_bdc_f else "PIK in Terms"

    # FV hierarchy (only if any data)
    fvl_total_f = float(fvl_total or 0)
    fv_hierarchy = None
    if fvl_total_f > 0:
        fv_hierarchy = {
            "level1": round(float(fvl_1 or 0) / fvl_total_f, 4),
            "level2": round(float(fvl_2 or 0) / fvl_total_f, 4),
            "level3": round(float(fvl_3 or 0) / fvl_total_f, 4),
            "coverage": round(fvl_total_f / total_fv_f, 4) if total_fv_f > 0 else None,
        }

    # Credit flags (only if any data)
    credit_flags = None
    credit_flag_count_i = int(credit_flag_count or 0)
    if credit_flag_count_i > 0:
        credit_flags = {
            "pctInDefault": round(float(default_fv or 0) / total_fv_f, 4) if total_fv_f > 0 else None,
            "pctInArrears": round(float(arrears_fv or 0) / total_fv_f, 4) if total_fv_f > 0 else None,
            "coverage": round(credit_flag_count_i / position_count_i, 4) if position_count_i > 0 else None,
        }

    result: dict = {
        "totalFv": _safe_round(total_fv_f, 0),
        "positionCount": position_count_i,
        "assetSplit": {
            "debt": _pct(debt_fv_f),
            "equity": _pct(float(equity_fv or 0)),
            "fund": _pct(float(fund_fv or 0)),
            "structured": _pct(float(structured_fv or 0)),
            "cash": _pct(float(cash_fv or 0)),
            "other": _pct(float(other_fv or 0)),
        },
        "assetClassSplit": {
            "privateCredit": _pct(float(ac_private_credit or 0)),
            "privateEquity": _pct(float(ac_private_equity or 0)),
            "realEstate": _pct(float(ac_real_estate or 0)),
            "structuredCredit": _pct(float(ac_structured_credit or 0)),
            "hedgeFund": _pct(float(ac_hedge_fund or 0)),
            "cash": _pct(float(ac_cash or 0)),
            "other": _pct(float(ac_other or 0)),
        },
        "exposureTypeSplit": {
            "direct": _pct(float(et_direct or 0)),
            "fund": _pct(float(et_fund_exp or 0)),
            "liquid": _pct(float(et_liquid or 0)),
        },
        "lienSplit": {
            "firstLien": round(first_lien_fv / debt_fv_f, 4) if debt_fv_f > 0 else None,
            "secondLien": round(float(second_lien_fv or 0) / debt_fv_f, 4) if debt_fv_f > 0 else None,
            "unsecured": round(float(unsecured_fv or 0) / debt_fv_f, 4) if debt_fv_f > 0 else None,
            "coverage": lien_coverage,
        },
        "rateTypeSplit": {
            "floating": round(float(floating_fv or 0) / debt_fv_f, 4) if debt_fv_f > 0 else None,
            "fixed": round(float(fixed_fv or 0) / debt_fv_f, 4) if debt_fv_f > 0 else None,
        },
        "wac": _safe_round(wac, 2),
        "wacCoverage": wac_coverage,
        "was": _safe_round(was, 2),
        "wam": _safe_round(wam, 1),
        "wamCoverage": wam_cov,
        "maturityBuckets": [
            {"label": "<1Y", "pct": _mat_pct(mat_0)},
            {"label": "1Y", "pct": _mat_pct(mat_1)},
            {"label": "2Y", "pct": _mat_pct(mat_2)},
            {"label": "3Y", "pct": _mat_pct(mat_3)},
            {"label": "4Y", "pct": _mat_pct(mat_4)},
            {"label": "5Y", "pct": _mat_pct(mat_5)},
            {"label": "6Y", "pct": _mat_pct(mat_6)},
            {"label": "7Y+", "pct": _mat_pct(mat_7p)},
        ],
        "unrealizedGl": {
            "aggregatePct": unrealized_agg_pct,
            "pctUnderwater": pct_underwater,
            "coverage": cost_coverage,
        },
        "concentration": {
            "top10Pct": top10_pct,
        },
        "pikExposure": {
            "pctOfDebtFv": pik_pct,
            "label": pik_label,
        },
        "fvHierarchy": fv_hierarchy,
        "creditFlags": credit_flags,
    }
    return result


def _compute_fund_top_holdings(
    con: duckdb.DuckDBPyConnection,
    cik: str,
) -> list[dict] | None:
    """Top 20 holdings by FV for a CIK's latest quarter."""
    rows = con.execute(f"""
        WITH cur AS (
            SELECT * FROM _holdings_latest
            WHERE cik = '{cik}' AND fair_value > 0
        ),
        total AS (SELECT SUM(fair_value) AS total_fv FROM cur),
        ranked AS (
            SELECT
                issuer_name,
                fair_value,
                fair_value / NULLIF((SELECT total_fv FROM total), 0) AS pct_of_portfolio,
                index_classification,
                interest_rate,
                -- Validate maturity: cap at 30 years from report_date
                CASE WHEN maturity_date IS NOT NULL
                          AND TRY_CAST(maturity_date AS DATE) IS NOT NULL
                          AND TRY_CAST(maturity_date AS DATE) > TRY_CAST(report_date AS DATE)
                          AND TRY_CAST(maturity_date AS DATE) < TRY_CAST(report_date AS DATE) + INTERVAL 30 YEAR
                     THEN maturity_date ELSE NULL
                END AS maturity_date_clean,
                CASE WHEN LOWER(issuer_name) LIKE '%second lien%'
                          OR LOWER(issuer_name) LIKE '%2nd lien%'
                          OR LOWER(issuer_name) LIKE '%junior%'
                     THEN 'Second Lien'
                     WHEN LOWER(issuer_name) LIKE '%unsecured%'
                          OR LOWER(issuer_name) LIKE '%subordinat%'
                          OR LOWER(issuer_name) LIKE '%mezzanine%'
                     THEN 'Unsecured'
                     WHEN LOWER(issuer_name) LIKE '%first lien%'
                          OR LOWER(issuer_name) LIKE '%1st lien%'
                          OR LOWER(issuer_name) LIKE '%senior secured%'
                     THEN 'First Lien'
                     ELSE NULL
                END AS lien_position,
                ROW_NUMBER() OVER (ORDER BY fair_value DESC) AS rn
            FROM cur
        )
        SELECT issuer_name, fair_value, pct_of_portfolio,
               index_classification, interest_rate, maturity_date_clean, lien_position
        FROM ranked WHERE rn <= 20
    """).fetchall()

    if not rows:
        return None

    cols = ["issuer_name", "fair_value", "pct_of_portfolio",
            "index_classification", "interest_rate", "maturity_date", "lien_position"]
    return [
        {
            "issuerName": r[0],
            "fairValue": _safe_round(r[1], 0),
            "pctOfPortfolio": _safe_round(r[2], 4),
            "assetCategory": r[3],
            "interestRate": _safe_round(r[4], 2),
            "maturityDate": r[5],
            "lienPosition": r[6],
        }
        for r in rows
    ]


def _export_fund_details(con: duckdb.DuckDBPyConnection) -> None:
    """Export per-CIK quarterly time series to fund_details/{cik}.json."""
    if not FUND_FINANCIALS_CSV.exists():
        logger.warning("fund_financials.csv not found -- skipping fund_details")
        return

    details_dir = FRONTEND_DATA_DIR / "fund_details"
    details_dir.mkdir(parents=True, exist_ok=True)

    # Load unified holdings into a temp table for exposure queries.
    # Use per-CIK latest quarter (each fund reports on its own schedule).
    has_holdings = UNIFIED_HOLDINGS_CSV.exists()
    if has_holdings:
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE _holdings_raw AS
            SELECT
                cik,
                issuer_name,
                CAST(fair_value AS DOUBLE) AS fair_value,
                TRY_CAST(interest_rate AS DOUBLE) AS interest_rate,
                TRY_CAST(basis_spread AS DOUBLE) AS basis_spread,
                asset_category,
                index_classification,
                coupon_type,
                maturity_date,
                report_date,
                exposure_type,
                asset_class,
                TRY_CAST(cost AS DOUBLE) AS cost,
                TRY_CAST(pik_rate AS DOUBLE) AS pik_rate,
                fair_value_level,
                source,
                nport_is_default,
                nport_are_interest_payments_in_arrears,
                nport_is_paid_in_kind
            FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE _holdings_latest AS
            WITH per_cik_max AS (
                SELECT cik, MAX(report_date) AS max_date
                FROM _holdings_raw
                GROUP BY cik
            )
            SELECT h.*
            FROM _holdings_raw h
            JOIN per_cik_max m ON h.cik = m.cik AND h.report_date = m.max_date
        """)
    else:
        # Create empty table so queries don't fail
        con.execute("""
            CREATE OR REPLACE TEMP TABLE _holdings_latest (
                cik VARCHAR, issuer_name VARCHAR, fair_value DOUBLE,
                interest_rate DOUBLE, basis_spread DOUBLE,
                asset_category VARCHAR, index_classification VARCHAR,
                coupon_type VARCHAR, maturity_date VARCHAR, report_date VARCHAR,
                exposure_type VARCHAR, asset_class VARCHAR, cost DOUBLE,
                pik_rate DOUBLE, fair_value_level VARCHAR, source VARCHAR,
                nport_is_default VARCHAR,
                nport_are_interest_payments_in_arrears VARCHAR,
                nport_is_paid_in_kind VARCHAR
            )
        """)

    # Filter: total_assets > $1M and at least one filing in the XBRL era
    ciks = con.execute(f"""
        SELECT cik FROM (
            SELECT cik,
                   MAX(TRY_CAST(total_assets AS DOUBLE)) AS max_assets,
                   MAX(report_quarter) AS last_q
            FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
            WHERE cik IS NOT NULL
            GROUP BY cik
        )
        WHERE max_assets > 1000000 AND last_q >= '2022q4'
    """).fetchall()

    # Numeric columns to export in time series
    numeric_cols = [
        "total_assets", "net_assets", "total_liabilities",
        "nav_per_share", "shares_outstanding", "borrowings",
        "total_investment_income", "net_investment_income",
        "leverage_ratio", "quarterly_return",
        "management_fee_pct", "expense_ratio_pct",
        "distribution_per_share", "distribution_rate",
        "total_return_pct", "income_per_share", "income_yield_pct",
        "portfolio_turnover", "asset_coverage_ratio",
        "unfunded_commitments", "premium_discount_pct",
        "distribution_rate_proxy", "redemption_pressure",
        "annualized_return",
        "monthly_return_1", "monthly_return_2", "monthly_return_3",
    ]

    # Optionally join identity data
    has_identity = FUND_IDENTITY_CSV.exists()
    identity_lookup: dict[str, dict] = {}
    if has_identity:
        id_rows = con.execute(f"""
            SELECT cik, adviser_name, ticker
            FROM read_csv_auto('{FUND_IDENTITY_CSV.as_posix()}', all_varchar=true)
        """).fetchall()
        for cik_id, adviser, ticker in id_rows:
            identity_lookup[str(cik_id)] = {
                "adviser": adviser or "",
                "ticker": ticker or "",
            }

    # Load BDC fund income for gross return computation
    income_lookup: dict[tuple[str, str], dict] = {}
    if BDC_FUND_INCOME_CSV.exists():
        def _to_float(v: Any) -> float | None:
            if v is None or str(v).strip() in ("", "nan"):
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        inc_rows = con.execute(f"""
            SELECT cik, report_quarter, total_expenses,
                   management_fee, incentive_fee, interest_expense,
                   duration_months
            FROM read_csv_auto('{BDC_FUND_INCOME_CSV.as_posix()}', all_varchar=true)
            WHERE cik IS NOT NULL AND report_quarter IS NOT NULL
        """).fetchall()
        for cik_i, qtr, tot_exp, mgmt, incent, int_exp, dm in inc_rows:
            income_lookup[(str(cik_i), str(qtr))] = {
                "total_expenses": _to_float(tot_exp),
                "management_fee": _to_float(mgmt),
                "incentive_fee": _to_float(incent),
                "interest_expense": _to_float(int_exp),
                "duration_months": _to_float(dm),
            }

    count = 0
    for (cik_val,) in ciks:
        rows = con.execute(f"""
            SELECT * FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
            WHERE cik = '{cik_val}' AND report_quarter >= '2022q4'
            ORDER BY report_quarter
        """).fetchdf()

        if rows.empty:
            continue

        series = []
        for _, r in rows.iterrows():
            entry: dict = {
                "quarter": r.get("report_quarter", ""),
                "reportDate": r.get("report_date", ""),
                "source": r.get("source", ""),
            }
            for col in numeric_cols:
                val = r.get(col)
                if val is not None and str(val).strip() not in ("", "nan"):
                    try:
                        entry[col] = round(float(val), 4)
                    except (ValueError, TypeError):
                        entry[col] = None
                else:
                    entry[col] = None

            # Compute gross_return_pct = net_return + fee_ratio
            source = entry.get("source")
            quarter = entry.get("quarter")
            if source == "companyfacts":
                net_ret = entry.get("total_return_pct")
                net_assets = entry.get("net_assets")
                if (net_ret is not None and net_assets is not None
                        and net_assets > 0 and quarter):
                    fi = income_lookup.get((str(cik_val), str(quarter)))
                    if fi:
                        dm = fi["duration_months"]
                        expenses = fi["total_expenses"]
                        if expenses is None:
                            expenses = (
                                (fi["management_fee"] or 0)
                                + (fi["incentive_fee"] or 0)
                                + (fi["interest_expense"] or 0)
                            ) or None
                        if dm and dm > 0 and expenses is not None:
                            fee_qtr = expenses * 3 / dm / net_assets
                            entry["gross_return_pct"] = round(
                                (net_ret / 100 + fee_qtr) * 100, 4
                            )
            elif source in ("nport", "ncen"):
                qr = entry.get("quarterly_return")
                er = entry.get("expense_ratio_pct")
                if qr is not None and er is not None:
                    entry["gross_return_pct"] = round(qr + er / 4, 4)

            series.append(entry)

        # Identity info
        id_info = identity_lookup.get(str(cik_val), {})

        # Compute exposure and top holdings
        exposure = _compute_fund_exposure(con, cik_val) if has_holdings else None
        top_holdings = _compute_fund_top_holdings(con, cik_val) if has_holdings else None

        fund_data = {
            "cik": cik_val,
            "name": str(rows.iloc[-1].get("entity_name", "")),
            "vehicleType": str(rows.iloc[-1].get("vehicle_type", "")),
            "adviser": id_info.get("adviser", ""),
            "ticker": id_info.get("ticker", ""),
            "series": series,
            "exposure": exposure,
            "topHoldings": top_holdings,
        }

        path = details_dir / f"{cik_val}.json"
        _write_bytes_retry(
            path,
            json.dumps(fund_data, default=str, separators=(",", ":")).encode("utf-8"),
        )
        count += 1

    # Cleanup temp tables
    con.execute("DROP TABLE IF EXISTS _holdings_latest")
    con.execute("DROP TABLE IF EXISTS _holdings_raw")

    logger.info("  Wrote %d fund detail JSON files in fund_details/", count)


def _export_fund_summary(con: duckdb.DuckDBPyConnection) -> None:
    """Export fund_summary.json -- universe aggregate stats."""
    if not FUND_FINANCIALS_CSV.exists():
        _write_json("fund_summary.json", {})
        return

    stats = con.execute(f"""
        WITH ff AS (
            SELECT * FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
        ),
        latest AS (
            SELECT cik, MAX(report_quarter) AS q
            FROM ff
            GROUP BY cik
            HAVING MAX(TRY_CAST(total_assets AS DOUBLE)) > 1000000
               AND MAX(report_quarter) >= '2022q4'
        ),
        snap AS (
            SELECT f.*
            FROM ff f
            JOIN latest l ON f.cik = l.cik AND f.report_quarter = l.q
        )
        SELECT
            COUNT(DISTINCT snap.cik) AS total_funds,
            SUM(CASE WHEN snap.vehicle_type = 'bdc' THEN 1 ELSE 0 END)
                AS bdc_count,
            SUM(CASE WHEN snap.vehicle_type = 'interval_fund'
                     THEN 1 ELSE 0 END) AS interval_count,
            SUM(CASE WHEN snap.vehicle_type = 'tender_offer_fund'
                     THEN 1 ELSE 0 END) AS tender_count,
            SUM(TRY_CAST(snap.total_assets AS DOUBLE)) AS total_aum,
            AVG(TRY_CAST(snap.leverage_ratio AS DOUBLE)) AS avg_leverage,
            AVG(TRY_CAST(snap.expense_ratio_pct AS DOUBLE))
                AS avg_expense_ratio,
            SUM(CASE WHEN snap.quarterly_return IS NOT NULL
                     THEN 1 ELSE 0 END) AS funds_with_returns,
            SUM(CASE WHEN snap.distribution_rate IS NOT NULL
                          OR snap.distribution_rate_proxy IS NOT NULL
                     THEN 1 ELSE 0 END) AS funds_with_distributions,
            (SELECT COUNT(DISTINCT report_quarter) FROM ff
             WHERE report_quarter >= '2022q4') AS total_quarters
        FROM snap
    """).fetchone()

    if stats is None:
        _write_json("fund_summary.json", {})
        return

    (total_funds, bdc_count, interval_count, tender_count,
     total_aum, avg_leverage, avg_expense, funds_with_returns,
     funds_with_dist, total_quarters) = stats

    _write_json("fund_summary.json", {
        "totalFunds": total_funds or 0,
        "bdcCount": bdc_count or 0,
        "intervalFundCount": interval_count or 0,
        "tenderOfferCount": tender_count or 0,
        "totalAum": _safe_round(total_aum, 0),
        "avgLeverageRatio": _safe_round(avg_leverage, 4),
        "avgExpenseRatioPct": _safe_round(avg_expense, 2),
        "fundsWithReturns": funds_with_returns or 0,
        "fundsWithDistributions": funds_with_dist or 0,
        "totalQuarters": total_quarters or 0,
    })


# ---------------------------------------------------------------------------
# Industry breakdown from BDC XBRL
# ---------------------------------------------------------------------------

def _export_industry_breakdown(con: duckdb.DuckDBPyConnection) -> None:
    """Export XBRL-derived industry sector breakdown.

    Reads ``bdc_sector_breakdown.csv`` and produces:
    - Index-level aggregate (sum FV per sector across all CIKs, latest quarter)
    - Per-CIK breakdown (for fund detail pages)
    """
    if not BDC_SECTOR_BREAKDOWN_FILE.exists():
        logger.warning("bdc_sector_breakdown.csv not found -- skipping")
        _write_json("industry_breakdown.json", {})
        return

    # Index-level: aggregate FV by GICS sub-industry for latest report_date.
    # Falls back to raw industry_sector if gics_sub_industry is missing.
    rows = con.execute(f"""
        WITH raw AS (
            SELECT * FROM read_csv_auto(
                '{BDC_SECTOR_BREAKDOWN_FILE.as_posix()}', all_varchar=true
            )
        ),
        latest AS (
            SELECT MAX(report_date) AS max_date FROM raw
        ),
        cur AS (
            SELECT * FROM raw
            WHERE report_date = (SELECT max_date FROM latest)
        ),
        agg AS (
            SELECT
                COALESCE(
                    NULLIF(gics_sub_industry, ''),
                    industry_sector
                ) AS sector_label,
                SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
                SUM(TRY_CAST(cost AS DOUBLE)) AS total_cost,
                AVG(TRY_CAST(pct_of_net_assets AS DOUBLE)) AS avg_pct,
                COUNT(DISTINCT cik) AS fund_count
            FROM cur
            WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
            GROUP BY sector_label
        ),
        with_pct AS (
            SELECT *,
                total_fv / NULLIF(SUM(total_fv) OVER (), 0) AS pct_of_total
            FROM agg
        )
        SELECT sector_label, total_fv, total_cost, avg_pct,
               fund_count, pct_of_total
        FROM with_pct
        ORDER BY total_fv DESC NULLS LAST
    """).fetchall()

    cols = ["sector_label", "total_fv", "total_cost", "avg_pct",
            "fund_count", "pct_of_total"]

    index_level = []
    for row in rows:
        d = dict(zip(cols, row))
        index_level.append({
            "sector": d["sector_label"],
            "totalFv": _safe_round(d["total_fv"], 0),
            "totalCost": _safe_round(d["total_cost"], 0),
            "avgPctOfNetAssets": _safe_round(d["avg_pct"], 4),
            "fundCount": d["fund_count"],
            "pctOfTotal": _safe_round(d["pct_of_total"], 4),
        })

    # Per-CIK: latest quarter per CIK (use GICS name, fall back to raw)
    cik_rows = con.execute(f"""
        WITH raw AS (
            SELECT * FROM read_csv_auto(
                '{BDC_SECTOR_BREAKDOWN_FILE.as_posix()}', all_varchar=true
            )
        ),
        per_cik_latest AS (
            SELECT cik, MAX(report_date) AS max_date
            FROM raw GROUP BY cik
        ),
        cur AS (
            SELECT r.*
            FROM raw r
            JOIN per_cik_latest l ON r.cik = l.cik AND r.report_date = l.max_date
        )
        SELECT
            cik,
            COALESCE(NULLIF(gics_sub_industry, ''), industry_sector) AS sector,
            TRY_CAST(fair_value AS DOUBLE) AS fair_value,
            TRY_CAST(cost AS DOUBLE) AS cost,
            TRY_CAST(pct_of_net_assets AS DOUBLE) AS pct_of_net_assets
        FROM cur
        WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
        ORDER BY cik, TRY_CAST(fair_value AS DOUBLE) DESC NULLS LAST
    """).fetchall()

    by_cik: dict[str, list[dict]] = {}
    for cik, sector, fv, cost_val, pct in cik_rows:
        by_cik.setdefault(cik, []).append({
            "sector": sector,
            "fairValue": _safe_round(fv, 0),
            "cost": _safe_round(cost_val, 0),
            "pctOfNetAssets": _safe_round(pct, 4),
        })

    _write_json("industry_breakdown.json", {
        "indexLevel": index_level,
        "byCik": by_cik,
    })


# ---------------------------------------------------------------------------
# Data quality dashboard
# ---------------------------------------------------------------------------

def _export_data_quality(con: duckdb.DuckDBPyConnection) -> None:
    """Export data quality metrics for the data quality dashboard page."""
    out: dict[str, Any] = {}

    # -- 1. GAV reconciliation histogram --
    if HOLDINGS_GAV_RECONCILIATION_FILE.exists():
        gav_rows = con.execute(f"""
            WITH raw AS (
                SELECT *,
                    TRY_CAST(gav_ratio_adjusted AS DOUBLE) AS adj,
                    TRY_CAST(gav_ratio AS DOUBLE) AS orig
                FROM read_csv_auto(
                    '{HOLDINGS_GAV_RECONCILIATION_FILE.as_posix()}',
                    all_varchar=true
                )
                WHERE comparison_source = 'investments_at_fair_value'
            ),
            with_ratio AS (
                SELECT COALESCE(adj, orig) AS ratio FROM raw
            )
            SELECT
                COUNT(*) AS total,
                MEDIAN(ratio) AS med,
                COUNT(CASE WHEN ratio >= 0.95 AND ratio <= 1.05 THEN 1 END) AS w95_105,
                COUNT(CASE WHEN ratio >= 0.80 AND ratio <= 1.20 THEN 1 END) AS w80_120,
                COUNT(CASE WHEN ratio < 0.3 THEN 1 END) AS b_lt03,
                COUNT(CASE WHEN ratio >= 0.3 AND ratio < 0.5 THEN 1 END) AS b_03_05,
                COUNT(CASE WHEN ratio >= 0.5 AND ratio < 0.65 THEN 1 END) AS b_05_065,
                COUNT(CASE WHEN ratio >= 0.65 AND ratio < 0.8 THEN 1 END) AS b_065_08,
                COUNT(CASE WHEN ratio >= 0.8 AND ratio < 0.9 THEN 1 END) AS b_08_09,
                COUNT(CASE WHEN ratio >= 0.9 AND ratio < 0.95 THEN 1 END) AS b_09_095,
                COUNT(CASE WHEN ratio >= 0.95 AND ratio < 0.98 THEN 1 END) AS b_095_098,
                COUNT(CASE WHEN ratio >= 0.98 AND ratio <= 1.02 THEN 1 END) AS b_098_102,
                COUNT(CASE WHEN ratio > 1.02 AND ratio <= 1.05 THEN 1 END) AS b_102_105,
                COUNT(CASE WHEN ratio > 1.05 AND ratio <= 1.1 THEN 1 END) AS b_105_11,
                COUNT(CASE WHEN ratio > 1.1 AND ratio <= 1.2 THEN 1 END) AS b_11_12,
                COUNT(CASE WHEN ratio > 1.2 AND ratio <= 1.5 THEN 1 END) AS b_12_15,
                COUNT(CASE WHEN ratio > 1.5 AND ratio <= 2.0 THEN 1 END) AS b_15_20,
                COUNT(CASE WHEN ratio > 2.0 THEN 1 END) AS b_gt20
            FROM with_ratio
        """).fetchone()

        if gav_rows and gav_rows[0]:
            total = gav_rows[0]
            out["gavReconciliation"] = {
                "histogram": [
                    {"bucket": "<0.3x", "count": gav_rows[4]},
                    {"bucket": "0.3-0.5x", "count": gav_rows[5]},
                    {"bucket": "0.5-0.65x", "count": gav_rows[6]},
                    {"bucket": "0.65-0.8x", "count": gav_rows[7]},
                    {"bucket": "0.8-0.9x", "count": gav_rows[8]},
                    {"bucket": "0.9-0.95x", "count": gav_rows[9]},
                    {"bucket": "0.95-0.98x", "count": gav_rows[10]},
                    {"bucket": "0.98-1.02x", "count": gav_rows[11]},
                    {"bucket": "1.02-1.05x", "count": gav_rows[12]},
                    {"bucket": "1.05-1.1x", "count": gav_rows[13]},
                    {"bucket": "1.1-1.2x", "count": gav_rows[14]},
                    {"bucket": "1.2-1.5x", "count": gav_rows[15]},
                    {"bucket": "1.5-2x", "count": gav_rows[16]},
                    {"bucket": ">2x", "count": gav_rows[17]},
                ],
                "totalCikQuarters": total,
                "median": _safe_round(gav_rows[1], 3),
                "within95_105Pct": _safe_round(
                    gav_rows[2] / total * 100 if total else 0, 1
                ),
                "within80_120Pct": _safe_round(
                    gav_rows[3] / total * 100 if total else 0, 1
                ),
            }

    # -- 2. Classification accuracy (cross-reference rules) --
    if CLASSIFICATION_VALIDATION_FILE.exists():
        cls_rows = con.execute(f"""
            SELECT rule, expected, condition,
                   TRY_CAST(total_rows AS INT) AS total_rows,
                   TRY_CAST(disagreement_count AS INT) AS disagreements,
                   TRY_CAST(disagreement_pct AS DOUBLE) AS pct
            FROM read_csv_auto(
                '{CLASSIFICATION_VALIDATION_FILE.as_posix()}',
                all_varchar=true
            )
            ORDER BY rule
        """).fetchall()

        out["classificationRules"] = [
            {
                "rule": r[0],
                "description": f"{r[1]} -> {r[2]}",
                "totalRows": r[3] or 0,
                "disagreements": r[4] or 0,
                "pct": _safe_round(r[5], 2),
            }
            for r in cls_rows
        ]

    # -- 3. Field fill rates + holdings by quarter + pipeline summary --
    if UNIFIED_HOLDINGS_CSV.exists():
        fill = con.execute(f"""
            WITH raw AS (
                SELECT * FROM read_csv_auto(
                    '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
                )
            )
            SELECT
                COUNT(*) AS total,
                COUNT(DISTINCT cik) AS n_ciks,
                MIN(report_date) AS earliest,
                MAX(report_date) AS latest,
                -- Field fill rates
                SUM(CASE WHEN TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                         AND TRY_CAST(fair_value AS DOUBLE) != 0 THEN 1 ELSE 0 END)
                    * 1.0 / COUNT(*) AS fill_fair_value,
                SUM(CASE WHEN TRY_CAST(cost AS DOUBLE) IS NOT NULL
                         AND TRY_CAST(cost AS DOUBLE) != 0 THEN 1 ELSE 0 END)
                    * 1.0 / COUNT(*) AS fill_cost,
                SUM(CASE WHEN TRY_CAST(interest_rate AS DOUBLE) IS NOT NULL
                         AND TRY_CAST(interest_rate AS DOUBLE) > 0 THEN 1 ELSE 0 END)
                    * 1.0 / COUNT(*) AS fill_interest_rate,
                SUM(CASE WHEN TRY_CAST(basis_spread AS DOUBLE) IS NOT NULL
                         AND TRY_CAST(basis_spread AS DOUBLE) > 0 THEN 1 ELSE 0 END)
                    * 1.0 / COUNT(*) AS fill_basis_spread,
                SUM(CASE WHEN TRY_CAST(principal_amount AS DOUBLE) IS NOT NULL
                         AND TRY_CAST(principal_amount AS DOUBLE) != 0 THEN 1 ELSE 0 END)
                    * 1.0 / COUNT(*) AS fill_principal,
                SUM(CASE WHEN maturity_date IS NOT NULL
                         AND TRIM(maturity_date) != '' THEN 1 ELSE 0 END)
                    * 1.0 / COUNT(*) AS fill_maturity,
                SUM(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                         AND TRY_CAST(shares_held AS DOUBLE) != 0 THEN 1 ELSE 0 END)
                    * 1.0 / COUNT(*) AS fill_shares,
                SUM(CASE WHEN TRY_CAST(pik_rate AS DOUBLE) IS NOT NULL
                         AND TRY_CAST(pik_rate AS DOUBLE) > 0 THEN 1 ELSE 0 END)
                    * 1.0 / COUNT(*) AS fill_pik_rate,
                -- Source split
                SUM(CASE WHEN source = 'bdc' THEN 1 ELSE 0 END) AS bdc_rows,
                SUM(CASE WHEN source = 'nport' THEN 1 ELSE 0 END) AS nport_rows,
                -- Unclassified rate
                SUM(CASE WHEN index_classification = 'UNCLASSIFIED'
                              OR index_classification IS NULL THEN 1 ELSE 0 END)
                    * 1.0 / COUNT(*) AS unclassified_pct
            FROM raw
        """).fetchone()

        if fill:
            out["fieldFillRates"] = [
                {"field": "Fair Value", "fillPct": _safe_round(fill[4], 4)},
                {"field": "Cost Basis", "fillPct": _safe_round(fill[5], 4)},
                {"field": "Interest Rate", "fillPct": _safe_round(fill[6], 4)},
                {"field": "Basis Spread", "fillPct": _safe_round(fill[7], 4)},
                {"field": "Principal", "fillPct": _safe_round(fill[8], 4)},
                {"field": "Maturity Date", "fillPct": _safe_round(fill[9], 4)},
                {"field": "Shares Held", "fillPct": _safe_round(fill[10], 4)},
                {"field": "PIK Rate", "fillPct": _safe_round(fill[11], 4)},
            ]
            out["pipelineSummary"] = {
                "totalHoldings": fill[0],
                "totalCiks": fill[1],
                "earliestDate": str(fill[2]),
                "latestDate": str(fill[3]),
                "bdcRows": fill[12],
                "nportRows": fill[13],
                "unclassifiedPct": _safe_round(fill[14], 4),
            }

        # Holdings by quarter
        qtr_rows = con.execute(f"""
            WITH raw AS (
                SELECT *,
                    CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                        || 'q'
                        || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                    AS quarter
                FROM read_csv_auto(
                    '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
                )
            )
            SELECT quarter,
                SUM(CASE WHEN source = 'bdc' THEN 1 ELSE 0 END) AS bdc,
                SUM(CASE WHEN source = 'nport' THEN 1 ELSE 0 END) AS nport,
                SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
                COUNT(DISTINCT cik) AS cik_count
            FROM raw
            GROUP BY quarter
            ORDER BY quarter
        """).fetchall()

        out["holdingsByQuarter"] = [
            {
                "quarter": r[0],
                "bdc": r[1],
                "nport": r[2],
                "totalFv": _safe_round(r[3], 0),
                "cikCount": r[4],
            }
            for r in qtr_rows
        ]

        # Classification breakdown (latest quarter-end date)
        cls_breakdown = con.execute(f"""
            WITH raw AS (
                SELECT * FROM read_csv_auto(
                    '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
                )
            ),
            latest AS (
                SELECT MAX(report_date) AS d FROM raw
                WHERE CAST(SUBSTRING(report_date, 9, 2) AS INT) >= 28
                  AND SUBSTRING(report_date, 6, 2)
                      IN ('03', '06', '09', '12')
            )
            SELECT
                COALESCE(index_classification, 'UNCLASSIFIED') AS cls,
                COUNT(*) AS n,
                SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
            FROM raw
            WHERE report_date = (SELECT d FROM latest)
            GROUP BY cls
            ORDER BY fv DESC NULLS LAST
        """).fetchall()

        total_fv = sum(float(r[2] or 0) for r in cls_breakdown)
        out["classificationBreakdown"] = [
            {
                "classification": r[0],
                "rows": r[1],
                "fv": _safe_round(r[2], 0),
                "fvPct": _safe_round(
                    float(r[2] or 0) / total_fv if total_fv else 0, 4
                ),
            }
            for r in cls_breakdown
        ]

    # -- 4. Third-party validation --
    if VALIDATION_REPORT_FILE.exists():
        tp_rows = con.execute(f"""
            SELECT source,
                COUNT(*) AS total,
                SUM(CASE WHEN issue = 'third_party_not_in_universe' THEN 1 ELSE 0 END)
                    AS missed
            FROM read_csv_auto(
                '{VALIDATION_REPORT_FILE.as_posix()}', all_varchar=true
            )
            GROUP BY source
        """).fetchall()

        out["thirdPartyValidation"] = [
            {
                "source": r[0],
                "total": r[1],
                "missed": r[2],
                "matchPct": _safe_round(
                    (r[1] - r[2]) / r[1] * 100 if r[1] else 0, 1
                ),
            }
            for r in tp_rows
        ]

    # -- 5. Reconciliation histogram grid (8 metrics) --
    recon_hists: list[dict[str, Any]] = []

    # 5a. GAV -- reuse already-computed data
    if "gavReconciliation" in out:
        g = out["gavReconciliation"]
        recon_hists.append({
            "id": "gav",
            "title": "GAV Reconciliation",
            "subtitle": "sum(FV) / reported investments at FV",
            "n": g["totalCikQuarters"],
            "median": g["median"],
            "centerValue": 1.0,
            "histogram": g["histogram"],
        })

    # Create temp tables so the 326 MB CSV is read only once
    uh_ok = False
    if UNIFIED_HOLDINGS_CSV.exists():
        try:
            con.execute(
                "CREATE OR REPLACE TEMP TABLE _uh AS SELECT * FROM "
                f"read_csv_auto('{UNIFIED_HOLDINGS_CSV.as_posix()}', "
                "all_varchar=true)"
            )
            uh_ok = True
        except Exception as exc:
            logger.warning("histogram: could not load unified holdings: %s", exc)

    ff_ok = False
    if FUND_FINANCIALS_CSV.exists():
        try:
            con.execute(
                "CREATE OR REPLACE TEMP TABLE _ff AS SELECT * FROM "
                f"read_csv_auto('{FUND_FINANCIALS_CSV.as_posix()}', "
                "all_varchar=true)"
            )
            ff_ok = True
        except Exception as exc:
            logger.warning("histogram: could not load fund_financials: %s", exc)

    # 5b. % of Net Assets Sum (BDC only, /100 so 1.0 = 100%)
    if uh_ok:
        try:
            rows = con.execute("""
                SELECT SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) / 100.0
                FROM _uh
                WHERE source = 'bdc'
                  AND TRY_CAST(pct_of_net_assets AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(pct_of_net_assets AS DOUBLE) != 0
                GROUP BY cik, report_date
                HAVING COUNT(*) >= 5
            """).fetchall()
            vals = [float(r[0]) for r in rows if r[0] is not None]
            h = _build_recon_hist(
                vals, "pct_net_assets", "% Net Assets Sum",
                "sum(pct_of_net_assets)/100, BDC only (>1 = levered)",
                edges=[0.5, 0.7, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6, 1.8, 2.0, 2.5, 3.0],
                labels=[
                    "<0.5", "0.5-0.7", "0.7-0.9", "0.9-1.0", "1.0-1.1",
                    "1.1-1.2", "1.2-1.4", "1.4-1.6", "1.6-1.8", "1.8-2.0",
                    "2.0-2.5", "2.5-3.0", ">3.0",
                ],
            )
            if h:
                recon_hists.append(h)
        except Exception as exc:
            logger.debug("histogram pct_net_assets skipped: %s", exc)

    # 5c. Position Count Ratio (QoQ)
    if uh_ok:
        try:
            rows = con.execute("""
                WITH q AS (
                    SELECT cik, report_date, COUNT(*) AS cnt
                    FROM _uh
                    WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                    GROUP BY cik, report_date
                ),
                wl AS (
                    SELECT *,
                        LAG(cnt) OVER (PARTITION BY cik ORDER BY report_date) AS prev
                    FROM q
                )
                SELECT cnt * 1.0 / prev FROM wl
                WHERE prev IS NOT NULL AND prev > 0
            """).fetchall()
            vals = [float(r[0]) for r in rows if r[0] is not None]
            h = _build_recon_hist(
                vals, "count_ratio", "Position Count Ratio",
                "QoQ position count change per CIK (1.0 = stable)",
            )
            if h:
                recon_hists.append(h)
        except Exception as exc:
            logger.debug("histogram count_ratio skipped: %s", exc)

    # 5d. FV Ratio (QoQ)
    if uh_ok:
        try:
            rows = con.execute("""
                WITH q AS (
                    SELECT cik, report_date,
                        SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                    FROM _uh
                    WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                    GROUP BY cik, report_date
                    HAVING SUM(TRY_CAST(fair_value AS DOUBLE)) > 0
                ),
                wl AS (
                    SELECT *,
                        LAG(fv) OVER (PARTITION BY cik ORDER BY report_date) AS prev
                    FROM q
                )
                SELECT fv / prev FROM wl
                WHERE prev IS NOT NULL AND prev > 0
            """).fetchall()
            vals = [float(r[0]) for r in rows if r[0] is not None]
            h = _build_recon_hist(
                vals, "fv_ratio", "FV Ratio",
                "QoQ total fair value change per CIK (1.0 = stable)",
            )
            if h:
                recon_hists.append(h)
        except Exception as exc:
            logger.debug("histogram fv_ratio skipped: %s", exc)

    # 5e. Yield Ratio (fund income / median position coupon)
    if FEE_UPLIFT_FILE.exists():
        try:
            rows = con.execute(f"""
                SELECT TRY_CAST(total_income_yield AS DOUBLE)
                       / NULLIF(TRY_CAST(median_all_in_coupon AS DOUBLE), 0)
                FROM read_csv_auto(
                    '{FEE_UPLIFT_FILE.as_posix()}', all_varchar=true
                )
                WHERE TRY_CAST(total_income_yield AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(median_all_in_coupon AS DOUBLE) > 0
            """).fetchall()
            vals = [float(r[0]) for r in rows if r[0] is not None]
            h = _build_recon_hist(
                vals, "yield_ratio", "Yield Ratio",
                "fund income yield / median position coupon",
            )
            if h:
                recon_hists.append(h)
        except Exception as exc:
            logger.debug("histogram yield_ratio skipped: %s", exc)

    # 5f. Cost-to-FV Ratio (sum(cost) / sum(FV) per CIK-quarter)
    if uh_ok:
        try:
            rows = con.execute("""
                SELECT SUM(TRY_CAST(cost AS DOUBLE))
                       / NULLIF(SUM(TRY_CAST(fair_value AS DOUBLE)), 0)
                FROM _uh
                WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(cost AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(cost AS DOUBLE) != 0
                GROUP BY cik, report_date
                HAVING COUNT(*) >= 5
                  AND SUM(TRY_CAST(fair_value AS DOUBLE)) > 0
            """).fetchall()
            vals = [float(r[0]) for r in rows if r[0] is not None]
            h = _build_recon_hist(
                vals, "cost_to_fv", "Cost / FV Ratio",
                "sum(cost) / sum(FV) per CIK-qtr (1.0 = at par)",
            )
            if h:
                recon_hists.append(h)
        except Exception as exc:
            logger.debug("histogram cost_to_fv skipped: %s", exc)

    # 5g. Distribution Coverage (income yield / distribution rate)
    if ff_ok:
        try:
            rows = con.execute("""
                SELECT TRY_CAST(income_yield_pct AS DOUBLE)
                       / NULLIF(TRY_CAST(distribution_rate AS DOUBLE), 0)
                FROM _ff
                WHERE TRY_CAST(income_yield_pct AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(income_yield_pct AS DOUBLE) > 0
                  AND TRY_CAST(distribution_rate AS DOUBLE) > 0
            """).fetchall()
            vals = [float(r[0]) for r in rows if r[0] is not None]
            h = _build_recon_hist(
                vals, "dist_coverage", "Distribution Coverage",
                "income yield / distribution rate (mixed period basis)",
            )
            if h:
                recon_hists.append(h)
        except Exception as exc:
            logger.debug("histogram dist_coverage skipped: %s", exc)

    # 5h. Leverage Reconciliation (implied vs reported leverage)
    if uh_ok and ff_ok:
        try:
            rows = con.execute("""
                WITH hsums AS (
                    SELECT cik, report_date,
                        SUM(TRY_CAST(fair_value AS DOUBLE)) AS sum_fv
                    FROM _uh
                    WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                    GROUP BY cik, report_date
                    HAVING SUM(TRY_CAST(fair_value AS DOUBLE)) > 0
                ),
                fin AS (
                    SELECT cik, report_date,
                        TRY_CAST(net_assets AS DOUBLE) AS na,
                        TRY_CAST(leverage_ratio AS DOUBLE) AS lev
                    FROM _ff
                    WHERE TRY_CAST(net_assets AS DOUBLE) > 0
                      AND TRY_CAST(leverage_ratio AS DOUBLE) > 0.01
                )
                SELECT (h.sum_fv - f.na) / h.sum_fv / f.lev
                FROM hsums h
                JOIN fin f ON h.cik = f.cik AND h.report_date = f.report_date
                WHERE h.sum_fv > f.na
            """).fetchall()
            vals = [float(r[0]) for r in rows if r[0] is not None]
            h = _build_recon_hist(
                vals, "leverage_recon", "Leverage Reconciliation",
                "implied leverage / reported leverage (1.0 = matches)",
            )
            if h:
                recon_hists.append(h)
        except Exception as exc:
            logger.debug("histogram leverage_recon skipped: %s", exc)

    # Clean up temp tables
    for tbl in ("_uh", "_ff"):
        try:
            con.execute(f"DROP TABLE IF EXISTS {tbl}")
        except Exception:
            pass

    # Drop histograms with too few observations to be meaningful
    recon_hists = [h for h in recon_hists if h["n"] >= 10]

    if recon_hists:
        out["reconciliationHistograms"] = recon_hists

    # -- 6. LLM fund classification validation --
    if LLM_FUND_VALIDATION_RESULTS_FILE.exists():
        try:
            import json as _json
            import pandas as pd
            res_df = pd.read_csv(LLM_FUND_VALIDATION_RESULTS_FILE, dtype=str)
            overall_row = res_df[res_df["metric"] == "overall"]
            if not overall_row.empty:
                overall = _json.loads(overall_row.iloc[0]["value"])
                class_rows = res_df[res_df["metric"].str.startswith("class_")]
                per_class = []
                for _, cr in class_rows.iterrows():
                    m = _json.loads(cr["value"])
                    per_class.append({
                        "label": m["label"],
                        "precision": _safe_round(m["precision"], 4),
                        "recall": _safe_round(m["recall"], 4),
                        "f1": _safe_round(m["f1"], 4),
                        "support": m["support"],
                    })
                out["llmFundValidation"] = {
                    "overallAccuracy": _safe_round(
                        overall["overallAccuracy"], 4
                    ),
                    "totalSamples": overall["totalSamples"],
                    "labels": overall["labels"],
                    "confusionMatrix": overall["confusionMatrix"],
                    "perClassMetrics": per_class,
                }
                logger.info("  LLM fund validation: %.1f%% accuracy (%d samples)",
                            overall["overallAccuracy"] * 100,
                            overall["totalSamples"])
        except Exception as exc:
            logger.warning("  LLM fund validation export failed: %s", exc)

    _write_json("data_quality.json", out)


# ---------------------------------------------------------------------------
# Landing page data visualizations
# ---------------------------------------------------------------------------

def _export_fund_index_returns(con: duckdb.DuckDBPyConnection) -> None:
    """Fund-level (NAV-based) index returns, chain-linked to index levels.

    Uses quarterly_return from fund_financials.csv (N-PORT total return for
    interval/tender funds, NAV-based reconstruction for BDCs).
    FV-weighted aggregate returns per quarter using total_assets as weight.
    """
    if not FUND_FINANCIALS_CSV.exists():
        logger.warning("fund_financials.csv not found -- skipping fund_index_returns")
        _write_json("fund_index_returns.json", {})
        return

    rows = con.execute(f"""
        WITH ff AS (
            SELECT * FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
        ),
        typed AS (
            SELECT
                cik,
                vehicle_type,
                report_quarter,
                TRY_CAST(quarterly_return AS DOUBLE) AS quarterly_return,
                TRY_CAST(total_assets AS DOUBLE) AS total_assets,
                TRY_CAST(nav_per_share AS DOUBLE) AS nav_per_share,
                TRY_CAST(distribution_per_share AS DOUBLE) AS dist_per_share
            FROM ff
            WHERE report_quarter >= '2022q4'
              {_quarter_cutoff_sql('report_quarter')}
              AND TRY_CAST(total_assets AS DOUBLE) > 1000000
        ),
        with_return AS (
            SELECT
                cik,
                vehicle_type,
                report_quarter,
                total_assets,
                COALESCE(
                    quarterly_return,
                    CASE
                        WHEN nav_per_share IS NOT NULL AND nav_per_share > 0 THEN
                            (nav_per_share
                             + COALESCE(dist_per_share, 0)
                             - LAG(nav_per_share) OVER (PARTITION BY cik ORDER BY report_quarter))
                            / NULLIF(LAG(nav_per_share) OVER (PARTITION BY cik ORDER BY report_quarter), 0)
                    END
                ) AS qtr_return
            FROM typed
        ),
        valid AS (
            SELECT * FROM with_return
            WHERE qtr_return IS NOT NULL
              AND ABS(qtr_return) < 0.5
        ),
        agg AS (
            SELECT
                report_quarter,
                CASE WHEN vehicle_type = 'bdc' THEN 'bdc'
                     WHEN vehicle_type = 'interval_fund' THEN 'interval_fund'
                     WHEN vehicle_type = 'tender_offer_fund' THEN 'tender_offer_fund'
                     ELSE 'other'
                END AS vtype,
                SUM(total_assets * qtr_return) / NULLIF(SUM(total_assets), 0) AS weighted_return,
                COUNT(DISTINCT cik) AS fund_count,
                SUM(total_assets) AS total_aum
            FROM valid
            GROUP BY report_quarter, vtype
        ),
        combined AS (
            SELECT
                report_quarter,
                'combined' AS vtype,
                SUM(total_assets * qtr_return) / NULLIF(SUM(total_assets), 0) AS weighted_return,
                COUNT(DISTINCT cik) AS fund_count,
                SUM(total_assets) AS total_aum
            FROM valid
            GROUP BY report_quarter
        ),
        all_series AS (
            SELECT * FROM agg WHERE vtype != 'other'
            UNION ALL
            SELECT * FROM combined
        )
        SELECT vtype, report_quarter, weighted_return, fund_count, total_aum
        FROM all_series
        ORDER BY vtype, report_quarter
    """).fetchall()

    # Group by series and chain-link to levels
    by_series: dict[str, list[dict]] = {}
    for vtype, quarter, ret, fund_count, total_aum in rows:
        by_series.setdefault(vtype, []).append({
            "quarter": quarter,
            "return": _safe_round(ret, 6),
            "fundCount": fund_count,
            "totalAum": _safe_round(total_aum, 0),
        })

    out: dict[str, list[dict]] = {}
    for vtype, series in by_series.items():
        series.sort(key=lambda x: x["quarter"])
        level = 100.0
        for row in series:
            r = row["return"] or 0
            level *= (1 + r)
            row["level"] = _safe_round(level, 2)
        # Prepend baseline
        if series:
            first_q = series[0]["quarter"]
            series.insert(0, {
                "quarter": _prev_quarter(first_q),
                "return": 0.0,
                "level": 100.0,
                "fundCount": 0,
                "totalAum": 0,
            })
        out[vtype] = series

    _write_json("fund_index_returns.json", out)
    logger.info("  fund_index_returns: %d series, %d total points",
                len(out), sum(len(v) for v in out.values()))


def _export_aum_time_series(con: duckdb.DuckDBPyConnection) -> None:
    """AUM growth by vehicle type over time."""
    if not FUND_FINANCIALS_CSV.exists():
        logger.warning("fund_financials.csv not found -- skipping aum_time_series")
        _write_json("aum_time_series.json", [])
        return

    rows = con.execute(f"""
        WITH ff AS (
            SELECT * FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
        ),
        typed AS (
            SELECT
                cik,
                vehicle_type,
                report_quarter,
                TRY_CAST(total_assets AS DOUBLE) AS total_assets
            FROM ff
            WHERE report_quarter >= '2022q4'
              {_quarter_cutoff_sql('report_quarter')}
              AND TRY_CAST(total_assets AS DOUBLE) > 1000000
        )
        SELECT
            report_quarter,
            SUM(CASE WHEN vehicle_type = 'bdc' THEN total_assets ELSE 0 END) AS bdc_aum,
            SUM(CASE WHEN vehicle_type = 'interval_fund' THEN total_assets ELSE 0 END) AS if_aum,
            SUM(CASE WHEN vehicle_type = 'tender_offer_fund' THEN total_assets ELSE 0 END) AS tof_aum,
            SUM(total_assets) AS total_aum,
            COUNT(DISTINCT CASE WHEN vehicle_type = 'bdc' THEN cik END) AS bdc_count,
            COUNT(DISTINCT CASE WHEN vehicle_type = 'interval_fund' THEN cik END) AS if_count,
            COUNT(DISTINCT CASE WHEN vehicle_type = 'tender_offer_fund' THEN cik END) AS tof_count
        FROM typed
        GROUP BY report_quarter
        ORDER BY report_quarter
    """).fetchall()

    out = []
    for (quarter, bdc_aum, if_aum, tof_aum, total_aum,
         bdc_count, if_count, tof_count) in rows:
        out.append({
            "quarter": quarter,
            "bdc": _safe_round(bdc_aum, 0),
            "intervalFund": _safe_round(if_aum, 0),
            "tenderOffer": _safe_round(tof_aum, 0),
            "total": _safe_round(total_aum, 0),
            "bdcCount": bdc_count,
            "intervalCount": if_count,
            "tenderCount": tof_count,
        })

    _write_json("aum_time_series.json", out)
    logger.info("  aum_time_series: %d quarters", len(out))


def _export_gics_sector_breakdown(con: duckdb.DuckDBPyConnection) -> None:
    """GICS sector breakdown from BDC XBRL industry-axis data.

    Top 15 sectors + Other + Unclassified (N-PORT holdings without sector).
    """
    bdc_sector_csv = BDC_SECTOR_BREAKDOWN_FILE
    if not bdc_sector_csv.exists():
        logger.warning("bdc_sector_breakdown.csv not found -- skipping gics_sector_breakdown")
        _write_json("gics_sector_breakdown.json", [])
        return

    # Get total FV across all holdings for denominator
    total_fv = 0.0
    if UNIFIED_HOLDINGS_CSV.exists():
        cutoff_date = (
            _quarter_to_date(INDEX_DISPLAY_END_QUARTER)
            if INDEX_DISPLAY_END_QUARTER else "9999-12-31"
        )
        total_row = con.execute(f"""
            WITH raw AS (
                SELECT * FROM read_csv_auto(
                    '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
                )
            ),
            latest AS (
                SELECT MAX(report_date) AS q FROM raw
                WHERE report_date <= '{cutoff_date}'
            )
            SELECT SUM(TRY_CAST(fair_value AS DOUBLE))
            FROM raw
            WHERE report_date = (SELECT q FROM latest)
              {_exclude_consumer_lending_sql('cik')}
        """).fetchone()
        if total_row and total_row[0]:
            total_fv = float(total_row[0])

    # Aggregate BDC sector data
    rows = con.execute(f"""
        WITH raw AS (
            SELECT * FROM read_csv_auto(
                '{bdc_sector_csv.as_posix()}', all_varchar=true
            )
        ),
        typed AS (
            SELECT
                industry_sector,
                TRY_CAST(fair_value AS DOUBLE) AS fair_value,
                cik,
                report_date
            FROM raw
            WHERE TRY_CAST(fair_value AS DOUBLE) > 0
              {_exclude_consumer_lending_sql('cik')}
        ),
        cutoff AS (
            SELECT MAX(report_date) AS q FROM typed
        ),
        latest AS (
            SELECT * FROM typed
            WHERE report_date = (SELECT q FROM cutoff)
        ),
        agg AS (
            SELECT
                industry_sector AS sector,
                SUM(fair_value) AS total_fv,
                COUNT(DISTINCT cik) AS fund_count
            FROM latest
            GROUP BY industry_sector
        )
        SELECT sector, total_fv, fund_count
        FROM agg
        ORDER BY total_fv DESC
    """).fetchall()

    if not rows:
        _write_json("gics_sector_breakdown.json", [])
        return

    classified_fv = sum(float(r[1]) for r in rows)
    grand_total = total_fv if total_fv > 0 else classified_fv

    # Top 15 + Other
    top_15 = rows[:15]
    other_rows = rows[15:]
    other_fv = sum(float(r[1]) for r in other_rows)

    out = []
    for sector, fv, fund_count in top_15:
        out.append({
            "sector": sector,
            "totalFv": _safe_round(fv, 0),
            "pctOfTotal": _safe_round(float(fv) / grand_total, 4) if grand_total > 0 else 0,
            "fundCount": fund_count,
        })

    if other_fv > 0:
        out.append({
            "sector": "Other",
            "totalFv": _safe_round(other_fv, 0),
            "pctOfTotal": _safe_round(other_fv / grand_total, 4) if grand_total > 0 else 0,
            "fundCount": None,
        })

    # Unclassified = grand total - classified
    unclassified_fv = grand_total - classified_fv
    if unclassified_fv > 0:
        out.append({
            "sector": "Unclassified",
            "totalFv": _safe_round(unclassified_fv, 0),
            "pctOfTotal": _safe_round(unclassified_fv / grand_total, 4) if grand_total > 0 else 0,
            "fundCount": None,
        })

    _write_json("gics_sector_breakdown.json", out)
    logger.info("  gics_sector_breakdown: %d sectors, $%.1fB classified of $%.1fB total",
                len(out), classified_fv / 1e9, grand_total / 1e9)


def _export_credit_risk(con: duckdb.DuckDBPyConnection) -> None:
    """Credit risk / distress time series for DIRECT_LENDING positions.

    Uses FV/par (fair value / principal amount) as the distress metric,
    which is the standard market convention for credit quality assessment
    (price relative to par, not to purchase cost).  This works uniformly
    across both BDC and N-PORT sources since both report principal_amount.

    4 mutually exclusive tiers (priority order):
    1. Deep distress: FV/par < 80%
    2. Distressed: 80% <= FV/par < 90%
    3. FV deterioration: 90% <= FV/par < 95%
    4. PIK active: pik_rate > 0 or nport_is_paid_in_kind='Y', not in 1-3

    Positions without usable par data (principal < $10K, or principal
    outside 0.1-10x of FV) are excluded from price tiers but still
    contribute to PIK.

    GAV filter: CIK-quarters where either DL-only or all-position FV /
    total_assets is between 0.7 and 1.3 are included.
    """
    if not UNIFIED_HOLDINGS_CSV.exists():
        logger.warning("unified holdings not found -- skipping credit_risk")
        _write_json("credit_risk.json", [])
        return

    has_fund_financials = FUND_FINANCIALS_CSV.exists()

    # GAV filter: include CIK-quarters where DL-only or all-position FV
    # reconciles to 70-130% of fund total assets.
    gav_cte = ""
    gav_join = ""
    if has_fund_financials:
        gav_cte = f""",
        ff AS (
            SELECT cik, report_quarter,
                   TRY_CAST(total_assets AS DOUBLE) AS total_assets
            FROM read_csv_auto('{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true)
            WHERE TRY_CAST(total_assets AS DOUBLE) > 0
        ),
        dl_gav AS (
            SELECT cik, report_quarter, SUM(fair_value) AS dl_fv
            FROM dl
            GROUP BY cik, report_quarter
        ),
        all_positions AS (
            SELECT cik,
                CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                || 'q'
                || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) AS report_quarter,
                TRY_CAST(fair_value AS DOUBLE) AS fair_value
            FROM read_csv_auto('{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true)
            WHERE TRY_CAST(fair_value AS DOUBLE) > 0
              AND report_date >= '2022-10-01'
              {_exclude_consumer_lending_sql('cik')}
        ),
        all_gav AS (
            SELECT cik, report_quarter, SUM(fair_value) AS all_fv
            FROM all_positions
            GROUP BY cik, report_quarter
        ),
        good_ciks AS (
            SELECT d.cik, d.report_quarter
            FROM dl_gav d
            JOIN all_gav a ON d.cik = a.cik AND d.report_quarter = a.report_quarter
            JOIN ff ON d.cik = ff.cik AND d.report_quarter = ff.report_quarter
            WHERE d.dl_fv / ff.total_assets BETWEEN 0.7 AND 1.3
               OR a.all_fv / ff.total_assets BETWEEN 0.7 AND 1.3
        )"""
        gav_join = """INNER JOIN good_ciks gc
              ON dl.cik = gc.cik AND dl.report_quarter = gc.report_quarter"""

    rows = con.execute(f"""
        WITH raw AS (
            SELECT * FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
        ),
        dl AS (
            SELECT
                cik,
                report_date,
                CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                || 'q'
                || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) AS report_quarter,
                TRY_CAST(fair_value AS DOUBLE) AS fair_value,
                TRY_CAST(principal_amount AS DOUBLE) AS principal,
                TRY_CAST(pik_rate AS DOUBLE) AS pik_rate,
                nport_is_paid_in_kind
            FROM raw
            WHERE index_classification = 'DIRECT_LENDING'
              AND TRY_CAST(fair_value AS DOUBLE) > 0
              AND report_date >= '2022-10-01'
              {_exclude_consumer_lending_sql('cik')}
        )
        {gav_cte},
        -- Assign tiers using FV/par (principal amount).
        -- Positions with usable par: principal > $10K and between
        -- 0.1x and 10x of FV (filters out share counts and bad data).
        with_tiers AS (
            SELECT
                dl.report_quarter,
                dl.fair_value,
                CASE
                    WHEN dl.principal > 10000
                         AND dl.principal BETWEEN dl.fair_value * 0.1
                                              AND dl.fair_value * 10.0
                    THEN CASE
                        WHEN dl.fair_value / dl.principal < 0.80 THEN 'deepDistress'
                        WHEN dl.fair_value / dl.principal < 0.90 THEN 'distressed'
                        WHEN dl.fair_value / dl.principal < 0.95 THEN 'fvDeterioration'
                        WHEN (COALESCE(dl.pik_rate, 0) > 0
                              OR dl.nport_is_paid_in_kind = 'Y') THEN 'pikActive'
                        ELSE 'healthy'
                    END
                    WHEN (COALESCE(dl.pik_rate, 0) > 0
                          OR dl.nport_is_paid_in_kind = 'Y') THEN 'pikActive'
                    ELSE 'healthy'
                END AS tier
            FROM dl
            {gav_join}
            WHERE dl.report_quarter IS NOT NULL
              {_quarter_cutoff_sql('dl.report_quarter')}
        )
        SELECT
            report_quarter,
            tier,
            COUNT(*) AS cnt,
            SUM(fair_value) AS tier_fv,
            SUM(COUNT(*)) OVER (PARTITION BY report_quarter) AS total_positions,
            SUM(SUM(fair_value)) OVER (PARTITION BY report_quarter) AS total_fv
        FROM with_tiers
        GROUP BY report_quarter, tier
        ORDER BY report_quarter, tier
    """).fetchall()

    # Group by quarter
    by_q: dict[str, dict] = {}
    for quarter, tier, cnt, tier_fv, total_positions, total_fv_q in rows:
        if quarter not in by_q:
            by_q[quarter] = {
                "quarter": quarter,
                "totalPositions": total_positions,
                "totalFv": _safe_round(total_fv_q, 0),
                "byCount": {},
                "byFv": {},
            }
        entry = by_q[quarter]
        total_pos = float(total_positions) if total_positions else 1
        total_fv_f = float(total_fv_q) if total_fv_q else 1
        entry["byCount"][tier] = _safe_round(float(cnt) / total_pos, 4)
        entry["byFv"][tier] = _safe_round(float(tier_fv) / total_fv_f, 4)

    # Ensure all tiers present in each quarter
    all_tiers = ["deepDistress", "distressed",
                 "fvDeterioration", "pikActive", "healthy"]
    out = []
    for q in sorted(by_q.keys()):
        entry = by_q[q]
        for t in all_tiers:
            entry["byCount"].setdefault(t, 0)
            entry["byFv"].setdefault(t, 0)
        out.append(entry)

    _write_json("credit_risk.json", out)
    logger.info("  credit_risk: %d quarters", len(out))


def _export_distribution_histogram(con: duckdb.DuckDBPyConnection) -> None:
    """Distribution rate histogram, latest quarter per CIK."""
    if not FUND_FINANCIALS_CSV.exists():
        logger.warning("fund_financials.csv not found -- skipping distribution_histogram")
        _write_json("distribution_histogram.json", {})
        return

    rows = con.execute(f"""
        WITH ff AS (
            SELECT * FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
        ),
        typed AS (
            SELECT
                cik,
                vehicle_type,
                report_quarter,
                TRY_CAST(distribution_rate AS DOUBLE) AS distribution_rate,
                TRY_CAST(total_assets AS DOUBLE) AS total_assets,
                ROW_NUMBER() OVER (PARTITION BY cik ORDER BY report_quarter DESC) AS rn
            FROM ff
            WHERE TRY_CAST(distribution_rate AS DOUBLE) > 0
              AND TRY_CAST(total_assets AS DOUBLE) > 1000000
              {_quarter_cutoff_sql('report_quarter')}
        ),
        latest AS (
            SELECT * FROM typed WHERE rn = 1
        )
        SELECT
            cik, vehicle_type, distribution_rate
        FROM latest
        ORDER BY distribution_rate
    """).fetchall()

    if not rows:
        _write_json("distribution_histogram.json", {})
        return

    # Build buckets: 0-2%, 2-4%, ..., 18-20%, 20%+
    # distribution_rate is stored in percentage form (e.g. 10.0 = 10%)
    bucket_edges = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
    bucket_labels = [
        "0-2%", "2-4%", "4-6%", "6-8%", "8-10%",
        "10-12%", "12-14%", "14-16%", "16-18%", "18-20%", "20%+",
    ]
    buckets = [{"bucket": label, "bdc": 0, "nonBdc": 0, "total": 0}
               for label in bucket_labels]

    rates = []
    for _, vehicle_type, dist_rate in rows:
        rate = float(dist_rate)
        rates.append(rate)
        is_bdc = vehicle_type == "bdc"
        placed = False
        for i, edge in enumerate(bucket_edges):
            if rate < edge:
                buckets[i]["bdc" if is_bdc else "nonBdc"] += 1
                buckets[i]["total"] += 1
                placed = True
                break
        if not placed:
            buckets[-1]["bdc" if is_bdc else "nonBdc"] += 1
            buckets[-1]["total"] += 1

    rates.sort()
    median = rates[len(rates) // 2] if rates else 0

    _write_json("distribution_histogram.json", {
        # Store median as decimal (0.10 = 10%) for frontend formatPercent()
        "median": _safe_round(median / 100, 4),
        "total": len(rates),
        "buckets": buckets,
    })
    logger.info("  distribution_histogram: %d funds, median %.1f%%",
                len(rates), median)


def _export_leverage_histogram(con: duckdb.DuckDBPyConnection) -> None:
    """Leverage ratio histogram, latest quarter per CIK."""
    if not FUND_FINANCIALS_CSV.exists():
        logger.warning("fund_financials.csv not found -- skipping leverage_histogram")
        _write_json("leverage_histogram.json", {})
        return

    rows = con.execute(f"""
        WITH ff AS (
            SELECT * FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
        ),
        typed AS (
            SELECT
                cik,
                vehicle_type,
                report_quarter,
                TRY_CAST(leverage_ratio AS DOUBLE) AS leverage_ratio,
                TRY_CAST(total_assets AS DOUBLE) AS total_assets,
                ROW_NUMBER() OVER (PARTITION BY cik ORDER BY report_quarter DESC) AS rn
            FROM ff
            WHERE TRY_CAST(leverage_ratio AS DOUBLE) IS NOT NULL
              AND TRY_CAST(leverage_ratio AS DOUBLE) >= 0
              AND TRY_CAST(total_assets AS DOUBLE) > 1000000
              {_quarter_cutoff_sql('report_quarter')}
        ),
        latest AS (
            SELECT * FROM typed WHERE rn = 1
        )
        SELECT
            cik, vehicle_type, leverage_ratio
        FROM latest
        ORDER BY leverage_ratio
    """).fetchall()

    if not rows:
        _write_json("leverage_histogram.json", {})
        return

    bucket_edges = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2]
    bucket_labels = ["<0.2x", "0.2-0.4x", "0.4-0.6x", "0.6-0.8x",
                     "0.8-1.0x", "1.0-1.2x", "1.2x+"]
    buckets = [{"bucket": label, "bdc": 0, "nonBdc": 0, "total": 0}
               for label in bucket_labels]

    ratios = []
    for _, vehicle_type, lev_ratio in rows:
        ratio = float(lev_ratio)
        ratios.append(ratio)
        is_bdc = vehicle_type == "bdc"
        placed = False
        for i, edge in enumerate(bucket_edges):
            if ratio < edge:
                buckets[i]["bdc" if is_bdc else "nonBdc"] += 1
                buckets[i]["total"] += 1
                placed = True
                break
        if not placed:
            buckets[-1]["bdc" if is_bdc else "nonBdc"] += 1
            buckets[-1]["total"] += 1

    ratios.sort()
    median = ratios[len(ratios) // 2] if ratios else 0

    _write_json("leverage_histogram.json", {
        "median": _safe_round(median, 4),
        "total": len(ratios),
        "buckets": buckets,
    })
    logger.info("  leverage_histogram: %d funds, median %.2fx",
                len(ratios), median)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def export_all() -> None:
    """Run all exports.  Called by ``pipeline.main --export-frontend``."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXPORTING FRONTEND JSON")
    logger.info("=" * 60)

    FRONTEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    ir = _export_index_returns(con)
    _export_index_summary(ir, con)
    _export_top_constituents(con)
    _export_sector_breakdown(con)
    _export_vehicle_contribution(con)
    _export_manager_concentration(con)
    _export_vehicle_concentration(con)
    _export_investee_concentration(con)
    _export_position_concentration(con)
    _export_concentration_curve(con)
    _export_portfolio_characteristics(con)
    _export_metadata(con, ir)
    _export_fund_list(con)
    _export_fund_details(con)
    _export_fund_summary(con)
    _export_industry_breakdown(con)
    _export_data_quality(con)

    # Landing page visualizations
    _export_fund_index_returns(con)
    _export_aum_time_series(con)
    _export_gics_sector_breakdown(con)
    _export_credit_risk(con)
    _export_distribution_histogram(con)
    _export_leverage_histogram(con)

    con.close()
    logger.info("Frontend export complete -- %d JSON files in %s",
                len(list(FRONTEND_DATA_DIR.glob("*.json"))),
                FRONTEND_DATA_DIR)
