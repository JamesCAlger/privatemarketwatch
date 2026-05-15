"""Frontend export helpers split from pipeline.export_frontend."""

from pipeline.export.helpers import *

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


