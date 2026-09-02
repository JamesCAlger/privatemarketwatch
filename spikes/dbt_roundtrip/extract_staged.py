"""Spike harness: stage BDC rows via the production path, pick the 3 CIKs
with the most duplicate-dimension-path rows, and extract deterministic
ground truth (the rows production's bdc_dim_ranked CTE drops).

Read-only w.r.t. data/output/; writes only under spikes/dbt_roundtrip/artifacts/.
Exit code 2 if no duplicate groups exist (replay impossible for this class).
"""
import sys
import time
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import agent_promoted, staging_bdc  # noqa: E402
from pipeline.config import BDC_HOLDINGS_FILE, BDC_HOLDINGS_PARQUET_FILE  # noqa: E402

ART = Path(__file__).resolve().parent / "artifacts"

NORM = ("regexp_replace(lower(trim(COALESCE(CAST({c} AS VARCHAR), ''))), "
        "'[^a-z0-9]+', ' ', 'g')")

# Production dedup key: pipeline/unified_holdings.py bdc_dim_ranked (lines 1033-1047)
KEY_EXPRS = [
    "cik",
    "accession_number",
    "report_date",
    NORM.format(c="issuer_name"),
    NORM.format(c="instrument_description"),
    "ROUND(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0), 0)",
    "ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0)",
    "ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)",
]
DIM_KEY = ", ".join(KEY_EXPRS)

# Production tiebreak order: pipeline/unified_holdings.py lines 1048-1053
DIM_ORDER = """
    LENGTH(COALESCE(CAST(issuer_name AS VARCHAR), '')),
    COALESCE(CAST(issuer_name AS VARCHAR), ''),
    COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
    COALESCE(CAST(accession_number AS VARCHAR), ''),
    COALESCE(CAST(src_context_id AS VARCHAR), '')
"""

KEY_SIG = (
    "concat_ws('|', cik, accession_number, CAST(report_date AS VARCHAR), "
    + NORM.format(c="issuer_name") + ", "
    + NORM.format(c="instrument_description") + ", "
    "CAST(CAST(ROUND(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0), 0) AS BIGINT) AS VARCHAR), "
    "CAST(CAST(ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0) AS BIGINT) AS VARCHAR), "
    "CAST(CAST(ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0) AS BIGINT) AS VARCHAR))"
)


def main() -> int:
    ART.mkdir(exist_ok=True)
    t0 = time.time()
    print("[1/5] Staging BDC rows via production path (staging_bdc._prepare_bdc) ...")
    raw_excl = agent_promoted.raw_staging_exclusions(
        agent_promoted.load_promoted_corrections())
    bdc_file = (BDC_HOLDINGS_PARQUET_FILE
                if BDC_HOLDINGS_PARQUET_FILE.exists() else BDC_HOLDINGS_FILE)
    bdc = staging_bdc._prepare_bdc(
        bdc_file=bdc_file, raw_exclusions=raw_excl, raw_exclusion_audits=[])
    print(f"      staged rows: {len(bdc)} in {time.time() - t0:.0f}s")

    con = duckdb.connect()
    con.register("bdc_part", bdc)
    sources = [r[0] for r in con.execute(
        "SELECT DISTINCT source FROM bdc_part").fetchall()]
    assert sources == ["bdc"], f"expected bdc-only staged frame, got {sources}"

    print("[2/5] Ranking CIKs by duplicate-dimension rows ...")
    con.execute(f"""
        COPY (
            SELECT cik, COUNT(*) AS dup_rows,
                   SUM(TRY_CAST(fair_value AS DOUBLE)) AS dup_fv
            FROM (SELECT *, COUNT(*) OVER (PARTITION BY {DIM_KEY}) AS _n
                  FROM bdc_part) t
            WHERE _n > 1
            GROUP BY cik ORDER BY dup_rows DESC, cik LIMIT 20
        ) TO '{(ART / "cik_selection.csv").as_posix()}' (HEADER)
    """)
    top = [r[0] for r in con.execute(
        f"SELECT cik FROM read_csv_auto('{(ART / 'cik_selection.csv').as_posix()}') "
        "ORDER BY dup_rows DESC, cik LIMIT 3").fetchall()]
    if not top:
        print("NO duplicate-dimension groups anywhere in staged data.")
        print("Replay impossible for this defect class; see plan Task 2 contingency.")
        return 2
    print(f"      top CIKs: {top}")
    cik_list = ", ".join(f"'{c}'" for c in top)

    print("[3/5] Applying subsidiary dedup (no_sub_dupes) to the CIK slice ...")
    # Verbatim port of pipeline/unified_holdings.py:998-1028; on a bdc-only
    # slice the upstream cross-source CTEs (deduped/no_dupes) are identity
    # because _source_count is always 1.
    n_i = NORM.format(c="nd2.issuer_name")
    n_i0 = NORM.format(c="nd.issuer_name")
    n_d = NORM.format(c="nd2.instrument_description")
    n_d0 = NORM.format(c="nd.instrument_description")
    con.execute(f"""
        CREATE TEMP TABLE bdc_top AS
        SELECT * FROM bdc_part WHERE cik IN ({cik_list});
        CREATE TEMP TABLE staged_predim AS
        SELECT * FROM bdc_top nd
        WHERE COALESCE(TRY_CAST(is_subsidiary AS INT), 0) = 0
           OR NOT EXISTS (
               SELECT 1 FROM bdc_top nd2
               WHERE nd2.cik = nd.cik
                 AND nd2.accession_number = nd.accession_number
                 AND nd2.report_date = nd.report_date
                 AND {n_i} = {n_i0}
                 AND {n_d} = {n_d0}
                 AND ROUND(COALESCE(TRY_CAST(nd2.fair_value AS DOUBLE), 0), 0)
                     = ROUND(COALESCE(TRY_CAST(nd.fair_value AS DOUBLE), 0), 0)
                 AND ROUND(COALESCE(TRY_CAST(nd2.principal_amount AS DOUBLE), 0), 0)
                     = ROUND(COALESCE(TRY_CAST(nd.principal_amount AS DOUBLE), 0), 0)
                 AND ROUND(COALESCE(TRY_CAST(nd2.shares_held AS DOUBLE), 0), 0)
                     = ROUND(COALESCE(TRY_CAST(nd.shares_held AS DOUBLE), 0), 0)
                 AND COALESCE(TRY_CAST(nd2.is_subsidiary AS INT), 0) = 0
           );
    """)
    con.execute(f"""
        COPY staged_predim TO '{(ART / "staged_predim.parquet").as_posix()}'
        (FORMAT PARQUET)
    """)

    print("[4/5] Computing ground truth (production _dim_rank > 1) ...")
    con.execute(f"""
        CREATE TEMP TABLE ranked AS
        SELECT *,
            'src:' || accession_number || ':' || COALESCE(src_context_id, '')
                AS source_row_id,
            {KEY_SIG} AS key_sig,
            ROW_NUMBER() OVER (
                PARTITION BY {DIM_KEY} ORDER BY {DIM_ORDER}
            ) AS _dim_rank
        FROM staged_predim;
        COPY (SELECT * FROM ranked WHERE _dim_rank > 1)
            TO '{(ART / "ground_truth_dropped.parquet").as_posix()}' (FORMAT PARQUET);
        COPY (SELECT key_sig, COUNT(*) AS group_size FROM ranked
              GROUP BY key_sig HAVING COUNT(*) > 1 ORDER BY key_sig)
            TO '{(ART / "ground_truth_groups.csv").as_posix()}' (HEADER);
    """)

    print("[5/5] Summary")
    n_slice, n_drop, n_grp = (
        con.execute("SELECT COUNT(*) FROM staged_predim").fetchone()[0],
        con.execute("SELECT COUNT(*) FROM ranked WHERE _dim_rank > 1").fetchone()[0],
        con.execute("SELECT COUNT(*) FROM (SELECT key_sig FROM ranked "
                    "GROUP BY key_sig HAVING COUNT(*) > 1)").fetchone()[0],
    )
    print(f"      slice rows: {n_slice}, dup groups: {n_grp}, dropped rows: {n_drop}")
    if n_drop == 0:
        print("Top CIKs have no dup rows after sub-dedup; see Task 2 contingency.")
        return 2
    null_ctx = con.execute(
        "SELECT COUNT(*) FROM ranked WHERE _dim_rank > 1 "
        "AND COALESCE(src_context_id, '') = ''").fetchone()[0]
    print(f"      dropped rows with empty src_context_id: {null_ctx} "
          "(these weaken kill criterion 1 if > 0)")
    print(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
