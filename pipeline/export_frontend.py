"""Export pre-computed JSON for the static Next.js frontend.

Reads pipeline output CSVs with DuckDB, writes aggregated JSON files to
``frontend/public/data/``.  No position-level data is exposed -- only
index-level time-series and aggregated summaries.

Usage:
    python -m pipeline.main --export-frontend
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from pipeline.config import (
    BDC_SECTOR_BREAKDOWN_FILE,
    CIK_TO_MANAGER_BRAND,
    FUND_IDENTITY_FILE,
    INDEX_DISPLAY_END_QUARTER,
    OUTPUT_DIR,
    PROJECT_ROOT,
)
from pipeline.index_returns import MIN_BEGIN_FV

logger = logging.getLogger(__name__)

FRONTEND_DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"

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

def _write_json(name: str, data: Any) -> Path:
    """Write *data* as compact JSON to ``FRONTEND_DATA_DIR / name``."""
    path = FRONTEND_DATA_DIR / name
    path.write_text(json.dumps(data, default=str, separators=(",", ":")),
                    encoding="utf-8")
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
                CASE WHEN pr.begin_basis_spread IS NOT NULL AND pr.begin_basis_spread > 0 THEN 'Floating'
                     WHEN pr.begin_interest_rate IS NOT NULL AND pr.begin_interest_rate > 0 THEN 'Fixed'
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
        path.write_text(
            json.dumps(fund_data, default=str, separators=(",", ":")),
            encoding="utf-8",
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

    con.close()
    logger.info("Frontend export complete -- %d JSON files in %s",
                len(list(FRONTEND_DATA_DIR.glob("*.json"))),
                FRONTEND_DATA_DIR)
