"""Frontend export helpers split from pipeline.export_frontend."""

from pipeline.export.helpers import *

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


