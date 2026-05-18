"""Frontend export helpers split from pipeline.export_frontend."""

from pipeline.export.helpers import *

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
            SELECT cik, MAX(TRY_CAST(report_date AS DATE)) AS d
            FROM ff
            GROUP BY cik
            HAVING MAX(TRY_CAST(total_assets AS DOUBLE)) > 1000000
               AND MAX(TRY_CAST(report_date AS DATE)) >= DATE '2022-10-01'
        ),
        snap AS (
            SELECT * FROM (
                SELECT f.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY f.cik
                        ORDER BY
                            TRY_CAST(f.report_date AS DATE) DESC NULLS LAST,
                            f.report_quarter DESC NULLS LAST
                    ) AS rn
            FROM ff f
                JOIN latest l
                  ON f.cik = l.cik
                 AND TRY_CAST(f.report_date AS DATE) = l.d
            )
            WHERE rn = 1
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
        ORDER BY
            TRY_CAST(f.total_assets AS DOUBLE) DESC NULLS LAST,
            COALESCE(f.entity_name, '') ASC,
            f.cik ASC
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
                   ROW_NUMBER() OVER (
                       ORDER BY
                           fair_value DESC NULLS LAST,
                           issuer_name ASC NULLS LAST,
                           index_classification ASC NULLS LAST
                   ) AS rn
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
                ROW_NUMBER() OVER (
                    ORDER BY
                        fair_value DESC NULLS LAST,
                        issuer_name ASC NULLS LAST,
                        index_classification ASC NULLS LAST,
                        maturity_date ASC NULLS LAST
                ) AS rn
            FROM cur
        )
        SELECT issuer_name, fair_value, pct_of_portfolio,
               index_classification, interest_rate, maturity_date_clean, lien_position
        FROM ranked WHERE rn <= 20
        ORDER BY rn
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
                   MAX(TRY_CAST(report_date AS DATE)) AS last_report_date
            FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
            WHERE cik IS NOT NULL
            GROUP BY cik
        )
        WHERE max_assets > 1000000 AND last_report_date >= DATE '2022-10-01'
        ORDER BY cik
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
            WHERE cik = '{cik_val}'
              AND TRY_CAST(report_date AS DATE) >= DATE '2022-10-01'
            ORDER BY TRY_CAST(report_date AS DATE), report_quarter
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
            SELECT cik, MAX(TRY_CAST(report_date AS DATE)) AS d
            FROM ff
            GROUP BY cik
            HAVING MAX(TRY_CAST(total_assets AS DOUBLE)) > 1000000
               AND MAX(TRY_CAST(report_date AS DATE)) >= DATE '2022-10-01'
        ),
        snap AS (
            SELECT * FROM (
                SELECT f.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY f.cik
                        ORDER BY
                            TRY_CAST(f.report_date AS DATE) DESC NULLS LAST,
                            f.report_quarter DESC NULLS LAST
                    ) AS rn
            FROM ff f
                JOIN latest l
                  ON f.cik = l.cik
                 AND TRY_CAST(f.report_date AS DATE) = l.d
            )
            WHERE rn = 1
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

