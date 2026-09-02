"""Decisive spike checks.

1. Group equality: packet key_sig set == ground-truth key_sig set
   (kill criterion 2 gate: the boundary test found exactly what
   production drops -- no more, no less).
2. Dropped-row identity: ground-truth dropped source_row_ids are a
   subset of packet source_row_ids, and counts reconcile as
   sum(group_size - 1) == dropped rows.
3. Incumbent view: what mechanism/localization does the residual
   classifier hold for the spike CIKs today (read-only query).
4. Determinism hash of bdc_dim_deduped (run twice via --hash-only to
   compare across two dbt builds).
"""
import json
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ART = HERE / "artifacts"
REPO = HERE.parents[1]
DETAIL = REPO / "data/output/source_reconciliation_source_only_detail.csv"
RESID = REPO / "data/output/source_reconciliation_residual_classification.csv"


def dedup_hash() -> str:
    con = duckdb.connect(str(ART / "spike.duckdb"), read_only=True)
    try:
        return con.execute(
            "SELECT md5(string_agg(source_row_id, ',' ORDER BY source_row_id)) "
            "FROM main.bdc_dim_deduped").fetchone()[0]
    finally:
        con.close()


def main() -> int:
    if "--hash-only" in sys.argv:
        print(f"dedup_output_hash: {dedup_hash()}")
        return 0

    packets = json.loads((ART / "packet.json").read_text(encoding="utf-8"))
    pkt_sigs = {p["key_sig"] for p in packets}
    pkt_row_ids = {rid for p in packets for rid in p["source_row_ids"]}
    ciks = sorted({p["cik"] for p in packets})

    con = duckdb.connect()
    gt_sigs = {r[0] for r in con.execute(
        f"SELECT key_sig FROM read_csv_auto('{(ART / 'ground_truth_groups.csv').as_posix()}')"
    ).fetchall()}
    gt_dropped = {r[0] for r in con.execute(
        f"SELECT source_row_id FROM '{(ART / 'ground_truth_dropped.parquet').as_posix()}'"
    ).fetchall()}

    groups_match = pkt_sigs == gt_sigs
    dropped_subset = gt_dropped <= pkt_row_ids
    counts_ok = sum(p["group_size"] - 1 for p in packets) == len(gt_dropped)

    cik_list = ", ".join(f"'{c}'" for c in ciks)
    incumbent = [dict(zip([d[0] for d in con.description], row))
                 for row in con.execute(f"""
        SELECT mechanism, disposition, is_blocking, COUNT(*) AS n
        FROM read_csv_auto('{DETAIL.as_posix()}')
        WHERE cik IN ({cik_list}) GROUP BY 1, 2, 3 ORDER BY n DESC
    """).fetchall()] if DETAIL.exists() else []
    resid = [dict(zip([d[0] for d in con.description], row))
             for row in con.execute(f"""
        SELECT mechanism, residual_class, status, COUNT(*) AS n
        FROM read_csv_auto('{RESID.as_posix()}')
        WHERE cik IN ({cik_list}) GROUP BY 1, 2, 3 ORDER BY n DESC
    """).fetchall()] if RESID.exists() else []

    verdict = {
        "groups_match": groups_match,
        "packet_groups": len(pkt_sigs),
        "ground_truth_groups": len(gt_sigs),
        "dropped_row_identity_match": dropped_subset and counts_ok,
        "spike_ciks": ciks,
        "incumbent_rows": incumbent,
        "incumbent_residual_rows": resid,
        "dedup_output_hash": dedup_hash(),
    }
    (ART / "verdict.json").write_text(
        json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    print(f"groups_match: {groups_match} "
          f"(packet {len(pkt_sigs)} vs ground truth {len(gt_sigs)})")
    print(f"dropped_row_identity_match: {dropped_subset and counts_ok}")
    print(f"incumbent mechanisms for spike CIKs: "
          f"{[r['mechanism'] for r in incumbent][:8]}")
    print(f"dedup_output_hash: {verdict['dedup_output_hash']}")
    print("wrote artifacts/verdict.json")
    return 0 if (groups_match and dropped_subset and counts_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
