"""Build blinded match-gold adjudication packets (chains + entity clusters).

Deterministic stratified sampling (frozen seed via md5 ordering, no RNG).
Chain strata: tier_random (per match tier), fv_jump (anomalous edges),
interior_singleton (missed-link hunting), drift_break (renamed-issuer pairs).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.match_quality import drift_break_candidates  # noqa: E402

SEED = "20260903"
SAMPLE_COLUMNS = ["packet_id", "packet_type", "stratum", "position_id", "cik"]


def _packet_id(*parts: str) -> str:
    digest = hashlib.md5(("|".join(parts) + SEED).encode("utf-8")).hexdigest()[:12]
    return f"MGP-{digest}"


def sample_chains(holdings_df, edges_df, *, per_tier=40, n_fv_jump=40,
                  n_interior_singleton=40, n_drift_break=40) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("h", holdings_df)
    con.register("e", edges_df)
    rows: list[dict] = []

    tier_sample = con.execute(f"""
        WITH ranked AS (
            SELECT position_id, cik, match_method,
                   ROW_NUMBER() OVER (
                       PARTITION BY match_method
                       ORDER BY md5(position_id || '{SEED}')) AS rn
            FROM (SELECT DISTINCT position_id, cik, match_method FROM e)
        )
        SELECT DISTINCT position_id, cik, match_method
        FROM ranked WHERE rn <= {per_tier}
        ORDER BY match_method, position_id
    """).df()
    for r in tier_sample.itertuples(index=False):   # sample-sized frame only
        rows.append({"packet_id": _packet_id("chain", "tier_random", r.position_id),
                     "packet_type": "chain", "stratum": "tier_random",
                     "position_id": r.position_id, "cik": str(r.cik)})

    jump = con.execute(f"""
        SELECT DISTINCT position_id, cik FROM e
        WHERE TRY_CAST(begin_fair_value AS DOUBLE) > 0
          AND TRY_CAST(end_fair_value AS DOUBLE) > 0
          AND GREATEST(TRY_CAST(begin_fair_value AS DOUBLE),
                       TRY_CAST(end_fair_value AS DOUBLE))
              / LEAST(TRY_CAST(begin_fair_value AS DOUBLE),
                      TRY_CAST(end_fair_value AS DOUBLE)) > 4.0
        ORDER BY md5(position_id || '{SEED}') LIMIT {n_fv_jump}
    """).df()
    for r in jump.itertuples(index=False):
        rows.append({"packet_id": _packet_id("chain", "fv_jump", r.position_id),
                     "packet_type": "chain", "stratum": "fv_jump",
                     "position_id": r.position_id, "cik": str(r.cik)})

    singles = con.execute(f"""
        WITH bdc AS (
            SELECT cik, report_date, position_id,
                   TRY_CAST(fair_value AS DOUBLE) AS fv
            FROM h WHERE source = 'bdc' AND position_id IS NOT NULL),
        pid1 AS (SELECT position_id FROM bdc GROUP BY position_id HAVING COUNT(*) = 1),
        bounds AS (SELECT cik, MIN(report_date) mn, MAX(report_date) mx
                   FROM bdc GROUP BY cik)
        SELECT b.position_id, b.cik FROM bdc b
        JOIN pid1 p ON b.position_id = p.position_id
        JOIN bounds bd ON b.cik = bd.cik
        WHERE b.fv > 0 AND b.report_date > bd.mn AND b.report_date < bd.mx
        ORDER BY md5(b.position_id || '{SEED}') LIMIT {n_interior_singleton}
    """).df()
    for r in singles.itertuples(index=False):
        rows.append({"packet_id": _packet_id("chain", "interior_singleton", r.position_id),
                     "packet_type": "chain", "stratum": "interior_singleton",
                     "position_id": r.position_id, "cik": str(r.cik)})

    drift = drift_break_candidates(holdings_df)
    if len(drift):
        drift = drift.assign(
            _o=[hashlib.md5((x + SEED).encode()).hexdigest()
                for x in drift["dropped_row_id"]]
        ).sort_values("_o").head(n_drift_break)
        pid_of = holdings_df.set_index("row_id")["position_id"]
        for r in drift.itertuples(index=False):
            rows.append({
                "packet_id": _packet_id("chain", "drift_break", r.dropped_row_id),
                "packet_type": "chain", "stratum": "drift_break",
                "position_id": pid_of.get(r.dropped_row_id, ""),
                "cik": str(r.cik)})

    out = pd.DataFrame(rows, columns=SAMPLE_COLUMNS)
    out = out.drop_duplicates(["stratum", "position_id"])
    return out.sort_values(["stratum", "packet_id"]).reset_index(drop=True)
