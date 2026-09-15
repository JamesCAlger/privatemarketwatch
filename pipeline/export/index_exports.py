"""Frontend export helpers split from pipeline.export_frontend."""

import math

from pipeline.export.helpers import *
from pipeline.config import BDC_LIEN_BREAKDOWN_FILE, BDC_DERIVATIVES_FILE


def _compute_risk_stats(series: list[dict]) -> dict:
    """Compute risk statistics from a sorted list of quarterly return dicts.

    Each dict must have ``fv_weighted_return`` (float|None) and
    ``index_level_fv`` (float|None).  Returns a dict with keys matching the
    frontend ``IndexRiskStats`` interface, or ``None`` values if fewer than
    2 usable quarters.
    """
    # Collect quarterly returns, skipping None
    returns = [
        s["fv_weighted_return"]
        for s in series
        if s.get("fv_weighted_return") is not None
    ]
    n = len(returns)
    if n < 2:
        return {
            "volatility": None,
            "sharpe": None,
            "maxDrawdown": None,
            "maxDrawdownQuarter": None,
            "bestQuarter": None,
            "bestQuarterLabel": None,
            "worstQuarter": None,
            "worstQuarterLabel": None,
            "pctPositiveQuarters": None,
            "positiveQuarters": None,
            "totalQuarters": n,
        }

    # --- Annualized volatility ---
    mean_r = sum(returns) / n
    var = sum((r - mean_r) ** 2 for r in returns) / (n - 1)  # sample variance
    quarterly_vol = math.sqrt(var)
    annualized_vol = quarterly_vol * math.sqrt(4)

    # --- Annualized return (geometric, from compounded quarterly returns) ---
    compounded = 1.0
    for r in returns:
        compounded *= (1 + r)
    total_return = compounded - 1
    years = n / 4
    annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # --- Sharpe ratio ---
    sharpe = (
        (annualized_return - RISK_FREE_RATE_ANNUAL) / annualized_vol
        if annualized_vol > 0
        else None
    )

    # --- Max drawdown from index_level_fv series ---
    levels = [
        (s["quarter"], s["index_level_fv"])
        for s in series
        if s.get("index_level_fv") is not None
    ]
    max_dd = 0.0
    max_dd_quarter = None
    if levels:
        peak = levels[0][1]
        for quarter, lvl in levels:
            if lvl > peak:
                peak = lvl
            dd = (lvl - peak) / peak if peak > 0 else 0.0
            if dd < max_dd:
                max_dd = dd
                max_dd_quarter = quarter

    # --- Best / worst quarter ---
    best_val = None
    best_label = None
    worst_val = None
    worst_label = None
    for s in series:
        r = s.get("fv_weighted_return")
        if r is None:
            continue
        if best_val is None or r > best_val:
            best_val = r
            best_label = s["quarter"]
        if worst_val is None or r < worst_val:
            worst_val = r
            worst_label = s["quarter"]

    # --- % positive quarters ---
    positive = sum(1 for r in returns if r > 0)

    return {
        "volatility": _safe_round(annualized_vol, 4),
        "sharpe": _safe_round(sharpe, 2),
        "maxDrawdown": _safe_round(max_dd, 4),
        "maxDrawdownQuarter": max_dd_quarter,
        "bestQuarter": _safe_round(best_val, 6),
        "bestQuarterLabel": best_label,
        "worstQuarter": _safe_round(worst_val, 6),
        "worstQuarterLabel": worst_label,
        "pctPositiveQuarters": _safe_round(positive / n, 4) if n > 0 else None,
        "positiveQuarters": positive,
        "totalQuarters": n,
    }


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
                  {_unlisted_bdc_filter_sql('cik')}
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
                  {_unlisted_bdc_filter_sql('pr.cik')}
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

        # Risk statistics
        risk_stats = _compute_risk_stats(series)

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
            "riskStats": risk_stats,
        })

    _write_json("index_summary.json", summaries)


def _export_top_constituents(con: duckdb.DuckDBPyConnection, *, snapshot, limit: int = 20) -> None:
    """Largest cohort positions by signed fair value, from the public snapshot.

    Reads the ``public_holdings`` temp table that ``public_snapshot`` materialised
    (cohort filter, latest public quarter, no sign filter), so the homepage table
    is drawn from exactly the population behind the headline fair value. Not
    keyed by index classification (v1 has no index surfaces) and not restricted
    to lending: cash, equity and fund rows compete on the same footing and are
    labelled via ``instrument``. Rate type is derived from the holdings columns:
    basis_spread > 0 -> Floating, else interest_rate > 0 -> Fixed, else null.
    """
    if snapshot is None:
        raise ValueError("_export_top_constituents requires the public snapshot")
    rows = con.execute("""
        WITH typed AS (
            SELECT issuer_name, entity_name, instrument, cik, row_id,
                CAST(public_fv AS DOUBLE) AS fv,
                TRY_CAST(nullif(trim(cost), '') AS DOUBLE) AS cost_num,
                CASE WHEN TRY_CAST(basis_spread AS DOUBLE) > 0 THEN 'Floating'
                     WHEN TRY_CAST(interest_rate AS DOUBLE) > 0 THEN 'Fixed'
                END AS rate_type
            FROM public_holdings
        )
        SELECT issuer_name, entity_name, instrument, fv, cost_num,
            CASE WHEN cost_num > 0 THEN (fv - cost_num) / cost_num * 100 END AS unrealized_gl_pct,
            rate_type
        FROM typed
        ORDER BY fv DESC NULLS LAST, cost_num DESC NULLS LAST,
            issuer_name ASC NULLS LAST, cik ASC NULLS LAST, row_id ASC NULLS LAST
        LIMIT ?
    """, [limit]).fetchall()

    positions = [{
        "issuerName": issuer_name,
        "vehicleName": entity_name,
        "instrument": instrument,
        "fairValue": _safe_round(fv, 0),
        "cost": _safe_round(cost_num, 0),
        "unrealizedGlPct": _safe_round(gl_pct, 2),
        "rateType": rate_type,
    } for issuer_name, entity_name, instrument, fv, cost_num, gl_pct, rate_type in rows]

    _write_json("top_constituents.json", {
        "asOf": snapshot["asOf"],
        "basis": snapshot["basis"],
        "scope": "all_cohort_holdings",
        "positionCount": snapshot["positionCount"],
        "positions": positions,
    })


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
                   ROW_NUMBER() OVER (
                       PARTITION BY cik
                       ORDER BY vehicle_type ASC NULLS LAST, cik
                   ) AS rn
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
        ORDER BY
            a.index_classification,
            a.total_fv DESC NULLS LAST,
            a.position_count DESC NULLS LAST,
            a.cik ASC NULLS LAST,
            a.entity_name ASC NULLS LAST,
            COALESCE(u.vehicle_type, 'unknown') ASC
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


# Lien tier -> output key
_LIEN_KEY = {
    "First Lien": "firstLien", "Second Lien": "secondLien",
    "Subordinated": "subordinated", "Unsecured": "unsecured", "Unknown": "unknown",
}


def _layer_lien_split(pp_rows, sub_rows, pct):
    """Combine filer lien subtotals with per-position lien_position.

    Parameters
    ----------
    pp_rows : list of (cik, lien_position, fv) -- per-position DL lien sums.
    sub_rows : list of (cik, lien_tier, fv) -- filer lien subtotals.
    pct : callable mapping an FV to a fraction of total DL FV.

    Per filer: if the lien subtotals reconcile to that filer's DL FV (all tiers
    non-negative, total within +5% and covering >= 50% of the filer's DL FV),
    use the subtotal tiers and route the uncovered remainder to Unknown.
    Otherwise use the per-position lien_position aggregation.  Returns the
    lienSplit dict, or None if there is nothing to compute.
    """
    from collections import defaultdict

    dl_fv: dict[str, float] = defaultdict(float)
    pp: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for cik, lien, fv in pp_rows:
        fv = float(fv or 0.0)
        dl_fv[cik] += fv
        pp[cik][_LIEN_KEY.get(str(lien), "unknown")] += fv
    if not dl_fv:
        return None

    sub: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for cik, tier, fv in sub_rows:
        sub[cik][_LIEN_KEY.get(str(tier), "unknown")] += float(fv or 0.0)

    out: dict[str, float] = defaultdict(float)
    n_sub = 0
    for cik, dl in dl_fv.items():
        s = sub.get(cik)
        s_tot = sum(s.values()) if s else 0.0
        s_min = min(s.values()) if s else 0.0
        # reconciliation gate: non-negative tiers, no over-count, >=50% coverage
        reconciles = bool(s) and s_min >= -1.0 and s_tot <= dl * 1.05 and s_tot >= dl * 0.5
        if reconciles:
            for k, v in s.items():
                out[k] += max(0.0, v)
            out["unknown"] += max(0.0, dl - s_tot)  # uncovered remainder is honest Unknown
            n_sub += 1
        else:
            for k, v in pp[cik].items():
                out[k] += v

    return {
        "firstLien": pct(out["firstLien"]),
        "secondLien": pct(out["secondLien"]),
        "subordinated": pct(out["subordinated"]),
        "unsecured": pct(out["unsecured"]),
        "unknown": pct(out["unknown"]),
        "source": "layered_subtotal_plus_position",
        "subtotalFilers": n_sub,
    }


def _export_portfolio_characteristics(con: duckdb.DuckDBPyConnection, *, snapshot=None) -> None:
    """Holdings-only public partitions, plus separately scoped lending analytics."""
    from pipeline.public_partitions import public_snapshot
    if not UNIFIED_HOLDINGS_CSV.exists():
        _write_json("portfolio_characteristics.json", {})
        return
    snapshot = snapshot or public_snapshot(con, UNIFIED_HOLDINGS_CSV,
        cutoff=_quarter_to_date(INDEX_DISPLAY_END_QUARTER) if INDEX_DISPLAY_END_QUARTER else "9999-12-31")
    as_of = snapshot["asOf"]
    if as_of is None:
        _write_json("portfolio_characteristics.json", {})
        return
    # Analytics require a positive weighting basis. That eligibility is separate
    # from headline/partition membership, which includes every retained row.
    stats = con.execute("""SELECT count(*),coalesce(sum(public_fv),0),
        sum(TRY_CAST(interest_rate AS DOUBLE)*public_fv) FILTER(WHERE public_fv>0 AND TRY_CAST(interest_rate AS DOUBLE)>0)
          /nullif(sum(public_fv) FILTER(WHERE public_fv>0 AND TRY_CAST(interest_rate AS DOUBLE)>0),0),
        sum(TRY_CAST(basis_spread AS DOUBLE)*public_fv) FILTER(WHERE public_fv>0 AND TRY_CAST(basis_spread AS DOUBLE)>0)
          /nullif(sum(public_fv) FILTER(WHERE public_fv>0 AND TRY_CAST(basis_spread AS DOUBLE)>0),0),
        sum((TRY_CAST(maturity_date AS DATE)-public_date)/365.25*public_fv)
          FILTER(WHERE public_fv>0 AND TRY_CAST(maturity_date AS DATE) IS NOT NULL)
          /nullif(sum(public_fv) FILTER(WHERE public_fv>0 AND TRY_CAST(maturity_date AS DATE) IS NOT NULL),0),
        count(*) FILTER(WHERE public_fv>0 AND TRY_CAST(interest_rate AS DOUBLE)>0),
        count(*) FILTER(WHERE public_fv>0 AND TRY_CAST(basis_spread AS DOUBLE)>0),
        count(*) FILTER(WHERE public_fv>0 AND TRY_CAST(maturity_date AS DATE) IS NOT NULL),
        coalesce(sum(public_fv) FILTER(WHERE lower(coupon_type) IN ('floating','variable')),0),
        coalesce(sum(public_fv) FILTER(WHERE lower(coupon_type)='fixed'),0)
        FROM public_holdings WHERE classification='DIRECT_LENDING'""").fetchone()
    pos_count,total_fv,wac,was,wam,wac_count,was_count,wam_count,floating_fv,fixed_fv = stats
    classification_fv = {r["label"]:r["totalFv"] for r in snapshot["partitions"]["classification"]}
    instrument = snapshot["partitions"]["instrument"]
    instrument_fv = {r["label"]:r["totalFv"] for r in instrument}
    def pct(value):
        return float(value)/float(total_fv) if total_fv else 0.0
    lien_split = {key:pct(instrument_fv.get(label,0)) for key,label in (
        ("firstLien","First Lien"),("secondLien","Second Lien"),("subordinated","Subordinated"),
        ("unsecured","Unsecured"),("unknown","Other Lending"))}
    lien_split["source"] = "position_lien_position"
    # Derivatives remain a separate diagnostic; none enter holdings partitions.
    portfolio_deriv_fv = financing_hedge_fv = financing_hedge_notional = 0.0
    if BDC_DERIVATIVES_FILE.exists():
        row = con.execute(f"""SELECT
          sum(TRY_CAST(net_fv AS DOUBLE)) FILTER(WHERE derivative_role='portfolio'),
          sum(TRY_CAST(net_fv AS DOUBLE)) FILTER(WHERE derivative_role='financing_hedge'),
          sum(TRY_CAST(notional AS DOUBLE)) FILTER(WHERE derivative_role='financing_hedge')
          FROM read_csv_auto('{BDC_DERIVATIVES_FILE.as_posix()}',all_varchar=true)
          WHERE substr(report_date,1,10)=? {_unlisted_bdc_filter_sql('cik')}""", [as_of]).fetchone()
        portfolio_deriv_fv,financing_hedge_fv,financing_hedge_notional = (float(v or 0) for v in row)
    _write_json("portfolio_characteristics.json", {
        "asOf":as_of,"positionCount":pos_count,"totalFv":float(total_fv),
        "portfolioPositionCount":snapshot["positionCount"],
        "portfolioFv":snapshot["portfolioFv"],"fairValueExact":snapshot["fairValueExact"],
        "missingFairValueCount":snapshot["missingFairValueCount"],
        "classificationFv":classification_fv,"instrumentBreakdown":instrument,
        "publicPartitionDelta":snapshot["publicPartitionDelta"],"basis":snapshot["basis"],
        "wac":_safe_round(wac,2),"was":_safe_round(was,2),"wam":_safe_round(wam,1),
        "wacCoverage":wac_count/pos_count if pos_count else 0,
        "wasCoverage":was_count/pos_count if pos_count else 0,
        "wamCoverage":wam_count/pos_count if pos_count else 0,
        "lienSplit":lien_split,"rateTypeSplit":{"floating":pct(floating_fv),"fixed":pct(fixed_fv)},
        "cashFv":classification_fv.get("CASH",0),"portfolioDerivativeFv":portfolio_deriv_fv,
        "financingHedgeFv":financing_hedge_fv,"financingHedgeNotional":financing_hedge_notional,
    })


def _date_to_quarter(rd: str) -> str | None:
    """'2026-03-31' -> '2026q1'; None if the date is malformed."""
    try:
        yr = int(rd[:4])
        mo = int(rd[5:7])
    except (ValueError, IndexError, TypeError):
        return None
    return f"{yr}q{(mo - 1) // 3 + 1}"


def _export_metadata(
    con: duckdb.DuckDBPyConnection,
    raw_returns: list[dict],
    *, snapshot=None,
) -> None:
    """As-of date, total AUM, vehicle counts, data vintage.

    When ``snapshot`` (from ``public_snapshot``) is given, the quarter, total
    AUM, holdings count, CIK count and unique-issuer count all come from the
    same ``public_holdings`` population as the headline. The read_csv path
    below is retained only for ``snapshot=None``.
    """
    # Latest quarter from the snapshot, else returns, else holdings
    latest_quarter = None
    as_of_date = None
    if snapshot is not None:
        as_of_date = snapshot.get("asOf")
        latest_quarter = _date_to_quarter(as_of_date) if as_of_date else None
    elif raw_returns:
        latest_quarter = max(r["quarter"] for r in raw_returns)

    if snapshot is None and latest_quarter is None and UNIFIED_HOLDINGS_CSV.exists():
        cutoff_date = _quarter_to_date(INDEX_DISPLAY_END_QUARTER) if INDEX_DISPLAY_END_QUARTER else '9999-12-31'
        result = con.execute(f"""
            SELECT MAX(report_date) FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
            WHERE report_date <= '{cutoff_date}'
              {_unlisted_bdc_filter_sql('cik')}
        """).fetchone()
        if result and result[0]:
            latest_quarter = _date_to_quarter(str(result[0]))

    # Vehicle counts from universe
    vehicle_counts = {"bdc": 0, "interval_fund": 0, "tender_offer_fund": 0}
    total_vehicles = 0
    if COMBINED_UNIVERSE_CSV.exists():
        vc_rows = con.execute(f"""
            SELECT vehicle_type, COUNT(DISTINCT cik) AS n
            FROM read_csv_auto('{COMBINED_UNIVERSE_CSV.as_posix()}')
            WHERE 1=1
              {_unlisted_bdc_filter_sql('cik')}
            GROUP BY vehicle_type
        """).fetchall()
        for vt, n in vc_rows:
            vehicle_counts[str(vt)] = n
            total_vehicles += n

    # Total AUM / counts: snapshot population when available, else legacy read_csv
    total_aum = 0
    holdings_count = 0
    cik_count = 0
    issuer_count = 0
    if snapshot is not None:
        total_aum = snapshot["portfolioFv"]
        holdings_count = snapshot["positionCount"]
        # Issuer identity: entity_id when resolved, else the issuer name. The
        # 'name:' prefix keeps an unresolved name from colliding with an id.
        cik_count, issuer_count = con.execute("""
            SELECT count(DISTINCT lpad(cik, 10, '0')),
                   count(DISTINCT coalesce(nullif(trim(entity_id), ''),
                                           'name:' || nullif(trim(issuer_name), '')))
            FROM public_holdings
        """).fetchone()
    elif UNIFIED_HOLDINGS_CSV.exists():
        cutoff_date = _quarter_to_date(INDEX_DISPLAY_END_QUARTER) if INDEX_DISPLAY_END_QUARTER else '9999-12-31'
        aum_row = con.execute(f"""
            WITH raw AS (
                SELECT * FROM read_csv_auto(
                    '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
                )
                WHERE 1=1
                  {_unlisted_bdc_filter_sql('cik')}
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

    # Legacy only: unique issuers among index constituents (position_returns)
    if snapshot is None and POSITION_RETURNS_CSV.exists():
        ir_row = con.execute(f"""
            WITH pr AS (
                SELECT * FROM read_csv_auto(
                    '{POSITION_RETURNS_CSV.as_posix()}', all_varchar=true
                )
                WHERE index_classification IS NOT NULL
                  AND index_classification != 'UNCLASSIFIED'
                  AND TRY_CAST(begin_fair_value AS DOUBLE) >= 100000
                  {_quarter_cutoff_sql('end_quarter')}
                  {_unlisted_bdc_filter_sql('cik')}
            ),
            latest AS (SELECT MAX(end_quarter) AS q FROM pr)
            SELECT COUNT(DISTINCT issuer_name)
            FROM pr
            WHERE end_quarter = (SELECT q FROM latest)
        """).fetchone()
        if ir_row:
            issuer_count = ir_row[0] or 0

    data_vintage = None
    if UNIFIED_HOLDINGS_CSV.exists():
        vintage_row = con.execute(f"""
            SELECT MAX(filing_date)
            FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
            WHERE filing_date IS NOT NULL AND TRIM(filing_date) != ''
              {_unlisted_bdc_filter_sql('cik')}
        """).fetchone()
        if vintage_row and vintage_row[0]:
            data_vintage = str(vintage_row[0])

    _write_json("metadata.json", {
        "asOfQuarter": latest_quarter,
        "asOfDate": as_of_date or (_quarter_to_date(latest_quarter) if latest_quarter else None),
        "totalAum": total_aum,
        "vehicleCount": total_vehicles,
        "bdcCount": vehicle_counts.get("bdc", 0),
        "intervalFundCount": vehicle_counts.get("interval_fund", 0),
        "tenderOfferCount": vehicle_counts.get("tender_offer_fund", 0),
        "holdingsCount": holdings_count,
        "cikCount": cik_count,
        "uniqueIssuers": issuer_count,
        "dataVintage": data_vintage,
    })


