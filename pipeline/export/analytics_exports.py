"""Frontend export helpers split from pipeline.export_frontend."""

from pipeline.export.helpers import *

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
                    ORDER BY
                        total_fv DESC NULLS LAST,
                        manager ASC NULLS LAST
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
                    ORDER BY
                        total_fv DESC NULLS LAST,
                        entity_name ASC NULLS LAST
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
                    ORDER BY
                        total_fv DESC NULLS LAST,
                        issuer_name ASC NULLS LAST
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
                ROW_NUMBER() OVER (
                    ORDER BY
                        total_fv DESC NULLS LAST,
                        entity ASC NULLS LAST
                ) AS rn,
                COUNT(*) OVER () AS total_count,
                SUM(total_fv) OVER () AS grand_total,
                SUM(total_fv) OVER (
                    ORDER BY
                        total_fv DESC NULLS LAST,
                        entity ASC NULLS LAST
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
                    ORDER BY
                        total_fv DESC NULLS LAST,
                        position_label ASC NULLS LAST
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
            gav_header = (
                HOLDINGS_GAV_RECONCILIATION_FILE.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()[0].split(",")
                if HOLDINGS_GAV_RECONCILIATION_FILE.stat().st_size
                else []
            )
            status_counts: list[dict[str, Any]] = []
            source_counts: list[dict[str, Any]] = []
            strong_cq = 0
            proxy_cq = 0
            if "reconciliation_status" in gav_header:
                status_counts = [
                    {"status": r[0], "count": r[1]}
                    for r in con.execute(f"""
                        SELECT reconciliation_status, COUNT(*)
                        FROM read_csv_auto(
                            '{HOLDINGS_GAV_RECONCILIATION_FILE.as_posix()}',
                            all_varchar=true
                        )
                        GROUP BY reconciliation_status
                        ORDER BY reconciliation_status
                    """).fetchall()
                ]
            if "comparison_source" in gav_header:
                source_counts = [
                    {"source": r[0] or "none", "count": r[1]}
                    for r in con.execute(f"""
                        SELECT COALESCE(comparison_source, ''), COUNT(*)
                        FROM read_csv_auto(
                            '{HOLDINGS_GAV_RECONCILIATION_FILE.as_posix()}',
                            all_varchar=true
                        )
                        GROUP BY COALESCE(comparison_source, '')
                        ORDER BY COALESCE(comparison_source, '')
                    """).fetchall()
                ]
            if "comparison_confidence" in gav_header:
                strong_cq = con.execute(f"""
                    SELECT COUNT(*)
                    FROM read_csv_auto(
                        '{HOLDINGS_GAV_RECONCILIATION_FILE.as_posix()}',
                        all_varchar=true
                    )
                    WHERE comparison_confidence = 'STRONG'
                """).fetchone()[0] or 0
                proxy_cq = con.execute(f"""
                    SELECT COUNT(*)
                    FROM read_csv_auto(
                        '{HOLDINGS_GAV_RECONCILIATION_FILE.as_posix()}',
                        all_varchar=true
                    )
                    WHERE comparison_confidence IN ('MODERATE', 'WEAK')
                """).fetchone()[0] or 0
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
                "statusCounts": status_counts,
                "comparisonSourceCounts": source_counts,
                "strongCikQuarters": strong_cq,
                "proxyCikQuarters": proxy_cq,
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

    # -- 3b. Unified quality tiers and column-level issue metrics --
    if DATA_QUALITY_METRICS_FILE.exists():
        try:
            tier_rows = con.execute(f"""
                SELECT validation_tier, COUNT(*) AS n
                FROM read_csv_auto(
                    '{DATA_QUALITY_METRICS_FILE.as_posix()}',
                    all_varchar=true
                )
                GROUP BY validation_tier
                ORDER BY validation_tier
            """).fetchall()
            out["validationTierCounts"] = [
                {"tier": r[0], "count": r[1]} for r in tier_rows
            ]
        except Exception as exc:
            logger.warning("  data quality tier export failed: %s", exc)

    if ROW_VALIDATION_ISSUES_FILE.exists():
        try:
            sev_rows = con.execute(f"""
                SELECT severity, COUNT(*) AS n
                FROM read_csv_auto(
                    '{ROW_VALIDATION_ISSUES_FILE.as_posix()}',
                    all_varchar=true,
                    quote='"'
                )
                GROUP BY severity
                ORDER BY severity
            """).fetchall()
            out["issueSeverityCounts"] = [
                {"severity": r[0], "count": r[1]} for r in sev_rows
            ]

            evidence_rows = con.execute(f"""
                SELECT evidence_strength, COUNT(*) AS n
                FROM read_csv_auto(
                    '{ROW_VALIDATION_ISSUES_FILE.as_posix()}',
                    all_varchar=true,
                    quote='"'
                )
                GROUP BY evidence_strength
                ORDER BY evidence_strength
            """).fetchall()
            out["issueEvidenceCounts"] = [
                {"evidenceStrength": r[0], "count": r[1]}
                for r in evidence_rows
            ]

            top_cols = con.execute(f"""
                SELECT "column", severity, COUNT(*) AS n
                FROM read_csv_auto(
                    '{ROW_VALIDATION_ISSUES_FILE.as_posix()}',
                    all_varchar=true,
                    quote='"'
                )
                WHERE "column" IS NOT NULL AND "column" != ''
                GROUP BY "column", severity
                ORDER BY n DESC
                LIMIT 20
            """).fetchall()
            out["topIssueColumns"] = [
                {"column": r[0], "severity": r[1], "count": r[2]}
                for r in top_cols
            ]
        except Exception as exc:
            logger.warning("  row validation issue export failed: %s", exc)

    if COLUMN_QUALITY_METRICS_FILE.exists():
        try:
            col_rows = con.execute(f"""
                SELECT
                    "column",
                    SUM(TRY_CAST(total_rows AS BIGINT)) AS total_rows,
                    SUM(TRY_CAST(filled_count AS BIGINT))
                        / NULLIF(SUM(TRY_CAST(total_rows AS BIGINT)), 0) AS fill_rate,
                    SUM(TRY_CAST(parseable_count AS BIGINT))
                        / NULLIF(SUM(TRY_CAST(filled_count AS BIGINT)), 0) AS parse_rate,
                    SUM(TRY_CAST(valid_count AS BIGINT))
                        / NULLIF(SUM(TRY_CAST(total_rows AS BIGINT)), 0) AS valid_rate,
                    SUM(TRY_CAST(fail_count AS BIGINT)) AS fail_count,
                    SUM(TRY_CAST(warn_count AS BIGINT)) AS warn_count
                FROM read_csv_auto(
                    '{COLUMN_QUALITY_METRICS_FILE.as_posix()}',
                    all_varchar=true
                )
                GROUP BY "column"
                ORDER BY fail_count DESC, warn_count DESC, "column"
            """).fetchall()
            out["columnQualityMetrics"] = [
                {
                    "column": r[0],
                    "totalRows": r[1] or 0,
                    "fillRate": _safe_round(r[2], 4),
                    "parseRate": _safe_round(r[3], 4),
                    "validRate": _safe_round(r[4], 4),
                    "failCount": r[5] or 0,
                    "warnCount": r[6] or 0,
                }
                for r in col_rows
            ]
        except Exception as exc:
            logger.warning("  column quality metric export failed: %s", exc)

    if POSITION_PURITY_METRICS_FILE.exists():
        try:
            purity = con.execute(f"""
                SELECT
                    SUM(TRY_CAST(subtotal_candidate_rows AS BIGINT)) AS subtotal_rows,
                    SUM(TRY_CAST(duplicate_dimension_candidate_rows AS BIGINT)) AS duplicate_rows,
                    SUM(TRY_CAST(comparative_period_rows AS BIGINT)) AS comparative_rows,
                    COUNT(CASE WHEN TRY_CAST(issue_rows AS BIGINT) > 0 THEN 1 END) AS affected_cik_quarters
                FROM read_csv_auto(
                    '{POSITION_PURITY_METRICS_FILE.as_posix()}',
                    all_varchar=true
                )
            """).fetchone()
            if purity:
                out["positionPurity"] = {
                    "issueCounts": {
                        "subtotalCandidate": int(purity[0] or 0),
                        "duplicateDimensionCandidate": int(purity[1] or 0),
                        "comparativePeriod": int(purity[2] or 0),
                    },
                    "affectedCikQuarters": int(purity[3] or 0),
                }
        except Exception as exc:
            logger.warning("  position purity export failed: %s", exc)

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
            ORDER BY source
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



def _export_gics_sector_breakdown(con: duckdb.DuckDBPyConnection) -> None:
    """GICS sector breakdown from reconciled BDC sectors plus holdings fallback.

    BDC CIK-quarters use reconciled sector filings when the CIK-quarter passes
    sector-to-holdings reconciliation.  Rejected or missing BDC CIK-quarters
    fall back to holdings-level GICS, and N-PORT always uses holdings-level GICS.
    """
    from pipeline.gics_mapping import _load_gics_hierarchy

    if not UNIFIED_HOLDINGS_CSV.exists():
        logger.warning("unified holdings not found -- skipping gics_sector_breakdown")
        _write_json("gics_sector_breakdown.json", [])
        return

    if (
        BDC_SECTOR_BREAKDOWN_FILE.exists()
        and not BDC_SECTOR_RECONCILIATION_FILE.exists()
    ):
        from pipeline.bdc_sector_reconciliation import (
            reconcile_bdc_sector_breakdown,
        )

        reconcile_bdc_sector_breakdown()

    cutoff_date = (
        _quarter_to_date(INDEX_DISPLAY_END_QUARTER)
        if INDEX_DISPLAY_END_QUARTER else "9999-12-31"
    )

    # Load GICS hierarchy and register as a DuckDB lookup table.
    # Aggregate to GICS sector level (11 categories) for a clean chart.
    hierarchy = _load_gics_hierarchy()
    seen_sectors: set[str] = set()
    hierarchy_rows: list[tuple[str, str]] = []
    for sub_ind, entry in hierarchy.items():
        sector = entry["sector"]
        hierarchy_rows.append((sub_ind, sector))
        seen_sectors.add(sector)
    # Also map industry group names to their sector (for extracted_industry fallback)
    seen_keys: set[str] = {r[0] for r in hierarchy_rows}
    for sub_ind, entry in hierarchy.items():
        grp = entry["industry_group"]
        if grp not in seen_keys:
            hierarchy_rows.append((grp, entry["sector"]))
            seen_keys.add(grp)
    # Identity mappings for sector names themselves
    for sector in seen_sectors:
        if sector not in seen_keys:
            hierarchy_rows.append((sector, sector))
            seen_keys.add(sector)
    con.execute("DROP TABLE IF EXISTS _gics_hierarchy")
    con.execute(
        "CREATE TEMP TABLE _gics_hierarchy (sub_industry VARCHAR, sector VARCHAR)"
    )
    con.executemany(
        "INSERT INTO _gics_hierarchy VALUES (?, ?)", hierarchy_rows
    )

    has_reconciled = BDC_SECTOR_BREAKDOWN_RECONCILED_FILE.exists()
    has_reconciliation = BDC_SECTOR_RECONCILIATION_FILE.exists()
    bdc_reconciled_cte = ""
    accepted_join = ""
    accepted_where = ""
    if has_reconciled and has_reconciliation:
        bdc_reconciled_cte = f""",
        reconciliation AS (
            SELECT *
            FROM read_csv_auto(
                '{BDC_SECTOR_RECONCILIATION_FILE.as_posix()}',
                all_varchar=true
            )
        ),
        accepted_bdc AS (
            SELECT DISTINCT cik, report_date
            FROM reconciliation
            WHERE reconciliation_status IN ('PASS', 'SCALE')
        ),
        bdc_sector AS (
            SELECT
                r.cik,
                r.report_date,
                TRY_CAST(r.reconciled_fair_value AS DOUBLE) AS fair_value,
                r.gics_sub_industry AS raw_industry,
                'bdc_sector_reconciled' AS source_bucket
            FROM read_csv_auto(
                '{BDC_SECTOR_BREAKDOWN_RECONCILED_FILE.as_posix()}',
                all_varchar=true
            ) r
            JOIN accepted_bdc ab
              ON r.cik = ab.cik AND r.report_date = ab.report_date
            JOIN latest_q l ON r.report_date = l.q
            WHERE TRY_CAST(r.reconciled_fair_value AS DOUBLE) > 0
        )"""
        accepted_join = """
            LEFT JOIN accepted_bdc ab
              ON latest.cik = ab.cik AND latest.report_date = ab.report_date
        """
        accepted_where = "AND ab.cik IS NULL"
    else:
        bdc_reconciled_cte = """,
        bdc_sector AS (
            SELECT
                CAST(NULL AS VARCHAR) AS cik,
                CAST(NULL AS VARCHAR) AS report_date,
                CAST(NULL AS DOUBLE) AS fair_value,
                CAST(NULL AS VARCHAR) AS raw_industry,
                CAST(NULL AS VARCHAR) AS source_bucket
            WHERE FALSE
        )"""

    rows = con.execute(f"""
        WITH raw AS (
            SELECT * FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
            WHERE 1=1
              {_unlisted_bdc_filter_sql('cik')}
        ),
        latest_q AS (
            SELECT MAX(report_date) AS q FROM raw
            WHERE report_date <= '{cutoff_date}'
        ),
        latest AS (
            SELECT
                cik,
                report_date,
                TRY_CAST(fair_value AS DOUBLE) AS fair_value,
                COALESCE(
                    NULLIF(gics_sub_industry, ''),
                    NULLIF(extracted_industry, '')
                ) AS raw_industry,
                index_classification,
                source
            FROM raw
            WHERE report_date = (SELECT q FROM latest_q)
              AND TRY_CAST(fair_value AS DOUBLE) > 0
              {_exclude_consumer_lending_sql('cik')}
        )
        {bdc_reconciled_cte},
        bdc_holdings_fallback AS (
            SELECT
                latest.cik,
                latest.report_date,
                latest.fair_value,
                latest.raw_industry,
                'bdc_holdings_fallback' AS source_bucket,
                latest.index_classification
            FROM latest
            {accepted_join}
            WHERE latest.source = 'bdc'
              {accepted_where}
        ),
        nport_holdings AS (
            SELECT
                cik,
                report_date,
                fair_value,
                raw_industry,
                'nport_holdings' AS source_bucket,
                index_classification
            FROM latest
            WHERE source <> 'bdc'
        ),
        hybrid AS (
            SELECT
                cik,
                report_date,
                fair_value,
                raw_industry,
                source_bucket,
                CAST(NULL AS VARCHAR) AS index_classification
            FROM bdc_sector
            UNION ALL
            SELECT * FROM bdc_holdings_fallback
            UNION ALL
            SELECT * FROM nport_holdings
        ),
        with_sector AS (
            SELECT
                COALESCE(
                    h.sector,
                    CASE hybrid.index_classification
                        WHEN 'PRIVATE_EQUITY_FUND' THEN 'Financials'
                        WHEN 'PRIVATE_CREDIT_FUND' THEN 'Financials'
                        WHEN 'HEDGE_FUND' THEN 'Financials'
                        WHEN 'STRUCTURED_CREDIT' THEN 'Financials'
                        WHEN 'REAL_ESTATE_FUND' THEN 'Real Estate'
                        WHEN 'DIRECT_REAL_ESTATE' THEN 'Real Estate'
                        ELSE NULL
                    END
                ) AS gics_sector,
                hybrid.fair_value,
                hybrid.cik,
                hybrid.source_bucket
            FROM hybrid
            LEFT JOIN _gics_hierarchy h ON hybrid.raw_industry = h.sub_industry
        ),
        agg AS (
            SELECT
                COALESCE(gics_sector, '_unclassified_') AS sector,
                SUM(fair_value) AS total_fv,
                COUNT(DISTINCT cik) AS fund_count,
                SUM(CASE WHEN source_bucket = 'bdc_sector_reconciled'
                         THEN fair_value ELSE 0 END) AS bdc_sector_reconciled_fv,
                SUM(CASE WHEN source_bucket = 'bdc_holdings_fallback'
                         THEN fair_value ELSE 0 END) AS bdc_holdings_fallback_fv,
                SUM(CASE WHEN source_bucket = 'nport_holdings'
                         THEN fair_value ELSE 0 END) AS nport_holdings_fv
            FROM with_sector
            GROUP BY gics_sector
        )
        SELECT sector, total_fv, fund_count, bdc_sector_reconciled_fv,
               bdc_holdings_fallback_fv, nport_holdings_fv
        FROM agg
        ORDER BY total_fv DESC
    """).fetchall()

    if not rows:
        _write_json("gics_sector_breakdown.json", [])
        return

    grand_total = sum(float(r[1]) for r in rows)

    # Separate classified sectors and the unknown residual. The public chart
    # displays shares on a total-FV denominator.
    classified = []
    unclassified_fv = 0.0
    unclassified_sources = [0.0, 0.0, 0.0]
    for sector, fv, fund_count, bdc_sector_fv, bdc_fallback_fv, nport_fv in rows:
        if sector == "_unclassified_":
            unclassified_fv += float(fv)
            unclassified_sources[0] += float(bdc_sector_fv or 0)
            unclassified_sources[1] += float(bdc_fallback_fv or 0)
            unclassified_sources[2] += float(nport_fv or 0)
        else:
            classified.append((
                sector,
                float(fv),
                fund_count,
                float(bdc_sector_fv or 0),
                float(bdc_fallback_fv or 0),
                float(nport_fv or 0),
            ))

    out = []
    for sector, fv, fund_count, bdc_sector_fv, bdc_fallback_fv, nport_fv in classified:
        out.append({
            "sector": sector,
            "totalFv": _safe_round(fv, 0),
            "pctOfTotal": _safe_round(fv / grand_total, 4) if grand_total > 0 else 0,
            "fundCount": fund_count,
            "sourceBreakdown": {
                "bdcSectorReconciledFv": _safe_round(bdc_sector_fv, 0),
                "bdcHoldingsFallbackFv": _safe_round(bdc_fallback_fv, 0),
                "nportHoldingsFv": _safe_round(nport_fv, 0),
            },
        })

    if unclassified_fv > 0:
        out.append({
            "sector": "Unknown",
            "totalFv": _safe_round(unclassified_fv, 0),
            "pctOfTotal": _safe_round(unclassified_fv / grand_total, 4) if grand_total > 0 else 0,
            "fundCount": None,
            "sourceBreakdown": {
                "bdcSectorReconciledFv": _safe_round(unclassified_sources[0], 0),
                "bdcHoldingsFallbackFv": _safe_round(unclassified_sources[1], 0),
                "nportHoldingsFv": _safe_round(unclassified_sources[2], 0),
            },
        })

    classified_fv = grand_total - unclassified_fv
    _write_json("gics_sector_breakdown.json", out)
    logger.info("  gics_sector_breakdown: %d classified groups + %s, $%.1fB classified of $%.1fB total (%.0f%%)",
                len(classified), "Unknown" if unclassified_fv > 0 else "no Unknown",
                classified_fv / 1e9, grand_total / 1e9,
                classified_fv / grand_total * 100 if grand_total > 0 else 0)


def _export_credit_risk(con: duckdb.DuckDBPyConnection) -> None:
    """BDC direct-lending credit stress signal time series.

    Signals are independent, not mutually exclusive:
    1. Deep distress: FV/principal_amount_usd < 80%
    2. Non-accrual: flagged in BDC XBRL footnotes/dimensions
    3. Marked below cost: FV/cost < 90%

    Non-accrual flags are read directly from the ``nonaccrual_footnote``
    and ``nonaccrual_dimension`` columns on unified holdings (extracted
    during BDC XBRL parsing).  N-PORT is excluded from this export.

    GAV filter: CIK-quarters where either DL-only or all-position FV /
    total_assets is between 0.7 and 1.3 are included.
    """
    if not UNIFIED_HOLDINGS_CSV.exists():
        logger.warning("unified holdings not found -- skipping credit_risk")
        _write_json("credit_risk.json", [])
        return

    has_fund_financials = FUND_FINANCIALS_CSV.exists()

    # GAV filter
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
              {_unlisted_bdc_filter_sql('cik')}
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
            WHERE 1=1
              {_unlisted_bdc_filter_sql('cik')}
        ),
        dl AS (
            SELECT
                cik,
                report_date,
                bdc_investment_identifier,
                CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                || 'q'
                || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) AS report_quarter,
                TRY_CAST(fair_value AS DOUBLE) AS fair_value,
                TRY_CAST(principal_amount_usd AS DOUBLE) AS principal,
                TRY_CAST(cost AS DOUBLE) AS cost,
                COALESCE(TRY_CAST(nonaccrual_footnote AS BOOLEAN), FALSE) AS _na_fn,
                COALESCE(TRY_CAST(nonaccrual_dimension AS BOOLEAN), FALSE) AS _na_dim
            FROM raw
            WHERE source = 'bdc'
              AND index_classification = 'DIRECT_LENDING'
              AND TRY_CAST(fair_value AS DOUBLE) > 0
              AND report_date >= '2022-10-01'
              {_exclude_consumer_lending_sql('cik')}
        )
        {gav_cte},
        with_tiers AS (
            SELECT
                dl.report_quarter,
                dl.fair_value,
                CASE WHEN dl._na_fn OR dl._na_dim THEN 1 ELSE 0 END AS is_nonaccrual,
                CASE
                    WHEN dl.principal > 10000
                         AND dl.principal BETWEEN dl.fair_value * 0.1
                                              AND dl.fair_value * 10.0
                         AND dl.fair_value / dl.principal < 0.80
                    THEN 1 ELSE 0
                END AS is_deep_distress,
                CASE
                    WHEN dl.cost > 10000
                         AND dl.cost BETWEEN dl.fair_value * 0.1
                                         AND dl.fair_value * 10.0
                         AND dl.fair_value / dl.cost < 0.90
                    THEN 1 ELSE 0
                END AS is_marked_below_cost
            FROM dl
            {gav_join}
            WHERE dl.report_quarter IS NOT NULL
              {_quarter_cutoff_sql('dl.report_quarter')}
        )
        SELECT
            report_quarter,
            COUNT(*) AS total_positions,
            SUM(fair_value) AS total_fv,
            SUM(is_deep_distress) AS deep_distress_count,
            SUM(is_nonaccrual) AS nonaccrual_count,
            SUM(is_marked_below_cost) AS marked_below_cost_count,
            SUM(CASE WHEN is_deep_distress = 1 THEN fair_value ELSE 0 END) AS deep_distress_fv,
            SUM(CASE WHEN is_nonaccrual = 1 THEN fair_value ELSE 0 END) AS nonaccrual_fv,
            SUM(CASE WHEN is_marked_below_cost = 1 THEN fair_value ELSE 0 END) AS marked_below_cost_fv
        FROM with_tiers
        GROUP BY report_quarter
        ORDER BY report_quarter
    """).fetchall()

    out = []
    for (
        quarter,
        total_positions,
        total_fv_q,
        deep_distress_count,
        nonaccrual_count,
        marked_below_cost_count,
        deep_distress_fv,
        nonaccrual_fv,
        marked_below_cost_fv,
    ) in rows:
        total_pos = float(total_positions) if total_positions else 1
        total_fv_f = float(total_fv_q) if total_fv_q else 1
        out.append({
            "quarter": quarter,
            "totalPositions": int(total_positions or 0),
            "totalFv": _safe_round(total_fv_q, 0),
            "byCount": {
                "deepDistress": _safe_round(float(deep_distress_count or 0) / total_pos, 4),
                "nonAccrual": _safe_round(float(nonaccrual_count or 0) / total_pos, 4),
                "markedBelowCost": _safe_round(float(marked_below_cost_count or 0) / total_pos, 4),
            },
            "byFv": {
                "deepDistress": _safe_round(float(deep_distress_fv or 0) / total_fv_f, 4),
                "nonAccrual": _safe_round(float(nonaccrual_fv or 0) / total_fv_f, 4),
                "markedBelowCost": _safe_round(float(marked_below_cost_fv or 0) / total_fv_f, 4),
            },
        })

    _write_json("credit_risk.json", out)
    logger.info("  credit_risk: %d quarters", len(out))


def _export_pik_eligibility(con: duckdb.DuckDBPyConnection) -> None:
    """Proportion of BDC direct-lending loans with PIK features, per quarter.

    A position is counted as PIK-eligible when the N-PORT paid-in-kind flag is
    set (``nport_is_paid_in_kind``) OR a PIK interest rate is populated
    (``pik_rate`` > 0).  This is a disclosure-based proxy for PIK *terms*, not
    proof of current PIK income -- see the PIK-terminology note in AGENTS.md.

    The universe mirrors ``_export_credit_risk`` exactly (unlisted BDC
    direct-lending positions, FV > 0, 2022q4 onward, behind the same GAV
    reconciliation filter) so the two charts share a denominator and can sit
    side by side.
    """
    if not UNIFIED_HOLDINGS_CSV.exists():
        logger.warning("unified holdings not found -- skipping pik_eligibility")
        _write_json("pik_eligibility.json", [])
        return

    has_fund_financials = FUND_FINANCIALS_CSV.exists()

    # GAV filter -- identical to _export_credit_risk.
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
              {_unlisted_bdc_filter_sql('cik')}
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
            WHERE 1=1
              {_unlisted_bdc_filter_sql('cik')}
        ),
        dl AS (
            SELECT
                cik,
                report_date,
                CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                || 'q'
                || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) AS report_quarter,
                TRY_CAST(fair_value AS DOUBLE) AS fair_value,
                CASE
                    WHEN COALESCE(TRY_CAST(nport_is_paid_in_kind AS BOOLEAN), FALSE)
                         OR (TRY_CAST(pik_rate AS DOUBLE) IS NOT NULL
                             AND TRY_CAST(pik_rate AS DOUBLE) > 0)
                    THEN 1 ELSE 0
                END AS is_pik
            FROM raw
            WHERE source = 'bdc'
              AND index_classification = 'DIRECT_LENDING'
              AND TRY_CAST(fair_value AS DOUBLE) > 0
              AND report_date >= '2022-10-01'
              {_exclude_consumer_lending_sql('cik')}
        )
        {gav_cte},
        filtered AS (
            SELECT dl.report_quarter, dl.fair_value, dl.is_pik
            FROM dl
            {gav_join}
            WHERE dl.report_quarter IS NOT NULL
              {_quarter_cutoff_sql('dl.report_quarter')}
        )
        SELECT
            report_quarter,
            COUNT(*) AS total_positions,
            SUM(fair_value) AS total_fv,
            SUM(is_pik) AS pik_count,
            SUM(CASE WHEN is_pik = 1 THEN fair_value ELSE 0 END) AS pik_fv
        FROM filtered
        GROUP BY report_quarter
        ORDER BY report_quarter
    """).fetchall()

    out = []
    for quarter, total_positions, total_fv_q, pik_count, pik_fv in rows:
        total_pos = float(total_positions) if total_positions else 1
        total_fv_f = float(total_fv_q) if total_fv_q else 1
        out.append({
            "quarter": quarter,
            "totalPositions": int(total_positions or 0),
            "totalFv": _safe_round(total_fv_q, 0),
            "pikCount": int(pik_count or 0),
            "pikFv": _safe_round(pik_fv, 0),
            "byCount": _safe_round(float(pik_count or 0) / total_pos, 4),
            "byFv": _safe_round(float(pik_fv or 0) / total_fv_f, 4),
        })

    _write_json("pik_eligibility.json", out)
    logger.info("  pik_eligibility: %d quarters", len(out))


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
                TRY_CAST(report_date AS DATE) AS report_date,
                TRY_CAST(distribution_rate AS DOUBLE) AS distribution_rate,
                TRY_CAST(total_assets AS DOUBLE) AS total_assets,
                ROW_NUMBER() OVER (
                    PARTITION BY cik
                    ORDER BY TRY_CAST(report_date AS DATE) DESC NULLS LAST,
                             report_quarter DESC NULLS LAST
                ) AS rn
            FROM ff
            WHERE TRY_CAST(distribution_rate AS DOUBLE) > 0
              AND TRY_CAST(total_assets AS DOUBLE) > 1000000
              {_quarter_cutoff_sql('report_quarter')}
              {_unlisted_bdc_filter_sql('cik')}
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
                TRY_CAST(report_date AS DATE) AS report_date,
                TRY_CAST(leverage_ratio AS DOUBLE) AS leverage_ratio,
                TRY_CAST(total_assets AS DOUBLE) AS total_assets,
                ROW_NUMBER() OVER (
                    PARTITION BY cik
                    ORDER BY TRY_CAST(report_date AS DATE) DESC NULLS LAST,
                             report_quarter DESC NULLS LAST
                ) AS rn
            FROM ff
            WHERE TRY_CAST(leverage_ratio AS DOUBLE) IS NOT NULL
              AND TRY_CAST(leverage_ratio AS DOUBLE) >= 0
              AND TRY_CAST(total_assets AS DOUBLE) > 1000000
              {_quarter_cutoff_sql('report_quarter')}
              {_unlisted_bdc_filter_sql('cik')}
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
# Spread analysis exports
# ---------------------------------------------------------------------------


def _export_spread_time_series(con: duckdb.DuckDBPyConnection) -> None:
    """FV-weighted average credit spread over time, DIRECT_LENDING only."""
    if not UNIFIED_HOLDINGS_CSV.exists():
        logger.warning("unified holdings not found -- skipping spread_time_series")
        _write_json("spread_time_series.json", [])
        return

    cutoff_date = (
        _quarter_to_date(INDEX_DISPLAY_END_QUARTER)
        if INDEX_DISPLAY_END_QUARTER else "9999-12-31"
    )

    rows = con.execute(f"""
        WITH raw AS (
            SELECT
                report_date,
                TRY_CAST(basis_spread AS DOUBLE) AS basis_spread,
                TRY_CAST(fair_value AS DOUBLE) AS fair_value
            FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
            WHERE index_classification = 'DIRECT_LENDING'
              AND TRY_CAST(basis_spread AS DOUBLE) > 0
              AND TRY_CAST(basis_spread AS DOUBLE) <= 15
              AND TRY_CAST(fair_value AS DOUBLE) > 0
              AND report_date <= '{cutoff_date}'
              {_unlisted_bdc_filter_sql('cik')}
              {_exclude_consumer_lending_sql('cik')}
        ),
        by_quarter AS (
            SELECT
                CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                    || 'q'
                    || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                AS quarter,
                SUM(basis_spread * fair_value) / SUM(fair_value) AS was,
                SUM(fair_value) AS total_fv,
                COUNT(*) AS position_count
            FROM raw
            GROUP BY quarter
            HAVING COUNT(*) >= 10
        )
        SELECT quarter, was, total_fv, position_count
        FROM by_quarter
        ORDER BY quarter
    """).fetchall()

    out = [
        {
            "quarter": r[0],
            "was": _safe_round(r[1], 6),
            "totalFv": _safe_round(r[2], 0),
            "positionCount": int(r[3]),
        }
        for r in rows
    ]

    _write_json("spread_time_series.json", out)
    logger.info("  spread_time_series: %d quarters", len(out))


def _export_spread_by_fund_size(con: duckdb.DuckDBPyConnection) -> None:
    """FV-weighted average spread by fund size tercile, latest quarter."""
    if not UNIFIED_HOLDINGS_CSV.exists() or not FUND_FINANCIALS_CSV.exists():
        logger.warning("unified holdings or fund_financials not found -- skipping spread_by_fund_size")
        _write_json("spread_by_fund_size.json", [])
        return

    cutoff_date = (
        _quarter_to_date(INDEX_DISPLAY_END_QUARTER)
        if INDEX_DISPLAY_END_QUARTER else "9999-12-31"
    )

    rows = con.execute(f"""
        WITH uh AS (
            SELECT
                cik,
                report_date,
                TRY_CAST(basis_spread AS DOUBLE) AS basis_spread,
                TRY_CAST(fair_value AS DOUBLE) AS fair_value
            FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
            WHERE index_classification = 'DIRECT_LENDING'
              AND TRY_CAST(basis_spread AS DOUBLE) > 0
              AND TRY_CAST(basis_spread AS DOUBLE) <= 15
              AND TRY_CAST(fair_value AS DOUBLE) > 0
              AND report_date <= '{cutoff_date}'
              {_unlisted_bdc_filter_sql('cik')}
              {_exclude_consumer_lending_sql('cik')}
        ),
        latest_q AS (
            SELECT MAX(report_date) AS q FROM uh
        ),
        latest AS (
            SELECT * FROM uh WHERE report_date = (SELECT q FROM latest_q)
        ),
        ff AS (
            SELECT cik,
                   TRY_CAST(total_assets AS DOUBLE) AS total_assets,
                   ROW_NUMBER() OVER (
                       PARTITION BY cik
                       ORDER BY TRY_CAST(report_date AS DATE) DESC NULLS LAST
                   ) AS rn
            FROM read_csv_auto(
                '{FUND_FINANCIALS_CSV.as_posix()}', all_varchar=true
            )
            WHERE TRY_CAST(total_assets AS DOUBLE) > 0
        ),
        latest_ff AS (
            SELECT cik, total_assets FROM ff WHERE rn = 1
        ),
        with_size AS (
            SELECT
                l.*,
                lf.total_assets,
                CASE
                    WHEN lf.total_assets < 1e9  THEN 1
                    WHEN lf.total_assets < 5e9  THEN 2
                    WHEN lf.total_assets < 15e9 THEN 3
                    ELSE 4
                END AS size_bucket
            FROM latest l
            JOIN latest_ff lf ON l.cik = lf.cik
        ),
        by_bucket AS (
            SELECT
                CASE size_bucket
                    WHEN 1 THEN '< $1B'
                    WHEN 2 THEN '$1-5B'
                    WHEN 3 THEN '$5-15B'
                    WHEN 4 THEN '> $15B'
                END AS bucket,
                size_bucket,
                SUM(basis_spread * fair_value) / SUM(fair_value) AS was,
                SUM(fair_value) AS total_fv,
                COUNT(*) AS position_count,
                COUNT(DISTINCT cik) AS fund_count
            FROM with_size
            GROUP BY size_bucket
        )
        SELECT bucket, was, total_fv, position_count, fund_count
        FROM by_bucket
        ORDER BY size_bucket
    """).fetchall()

    out = [
        {
            "bucket": r[0],
            "was": _safe_round(r[1], 6),
            "totalFv": _safe_round(r[2], 0),
            "positionCount": int(r[3]),
            "fundCount": int(r[4]),
        }
        for r in rows
    ]

    _write_json("spread_by_fund_size.json", out)
    logger.info("  spread_by_fund_size: %d buckets", len(out))


def _export_spread_by_lien(con: duckdb.DuckDBPyConnection) -> None:
    """FV-weighted average spread by lien position, latest quarter."""
    if not UNIFIED_HOLDINGS_CSV.exists():
        logger.warning("unified holdings not found -- skipping spread_by_lien")
        _write_json("spread_by_lien.json", [])
        return

    cutoff_date = (
        _quarter_to_date(INDEX_DISPLAY_END_QUARTER)
        if INDEX_DISPLAY_END_QUARTER else "9999-12-31"
    )

    rows = con.execute(f"""
        WITH uh AS (
            SELECT
                lien_position,
                TRY_CAST(basis_spread AS DOUBLE) AS basis_spread,
                TRY_CAST(fair_value AS DOUBLE) AS fair_value,
                report_date
            FROM read_csv_auto(
                '{UNIFIED_HOLDINGS_CSV.as_posix()}', all_varchar=true
            )
            WHERE index_classification = 'DIRECT_LENDING'
              AND TRY_CAST(basis_spread AS DOUBLE) > 0
              AND TRY_CAST(basis_spread AS DOUBLE) <= 15
              AND TRY_CAST(fair_value AS DOUBLE) > 0
              AND report_date <= '{cutoff_date}'
              {_unlisted_bdc_filter_sql('cik')}
              {_exclude_consumer_lending_sql('cik')}
        ),
        latest_q AS (
            SELECT MAX(report_date) AS q FROM uh
        ),
        latest AS (
            SELECT * FROM uh WHERE report_date = (SELECT q FROM latest_q)
        ),
        by_lien AS (
            SELECT
                COALESCE(NULLIF(lien_position, ''), 'Unknown') AS lien,
                SUM(basis_spread * fair_value) / SUM(fair_value) AS was,
                SUM(fair_value) AS total_fv,
                COUNT(*) AS position_count
            FROM latest
            GROUP BY lien
            HAVING COUNT(*) >= 5
        ),
        with_pct AS (
            SELECT *,
                total_fv / NULLIF(SUM(total_fv) OVER (), 0) AS pct_of_total
            FROM by_lien
        )
        SELECT lien, was, total_fv, position_count, pct_of_total
        FROM with_pct
        ORDER BY total_fv DESC
    """).fetchall()

    out = [
        {
            "lien": r[0],
            "was": _safe_round(r[1], 6),
            "totalFv": _safe_round(r[2], 0),
            "positionCount": int(r[3]),
            "pctOfTotal": _safe_round(r[4], 4),
        }
        for r in rows
    ]

    _write_json("spread_by_lien.json", out)
    logger.info("  spread_by_lien: %d lien types", len(out))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

