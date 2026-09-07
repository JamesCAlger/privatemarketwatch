"""Recall check on an interior-singleton gold batch: for every MISSED_LINK proposed
pair, is the pair chained (same position_id) in the current production build and in
the baseline snapshot?  Also reports the packet-level verdict mix.

Usage: python recall_check.py [batch_id]   (default mg5_recall)
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
BATCH = sys.argv[1] if len(sys.argv) > 1 else "mg5_recall"
OUT = Path(__file__).resolve().parent / "out" / BATCH
CUR = REPO / "data/output/private_markets_holdings.csv"
BASE = REPO / "data/snapshots/baseline/data/output/private_markets_holdings.csv"

gp = pd.read_csv(OUT / "gold_packets.csv", dtype=str).fillna("")
print("packet verdicts:", gp["verdict"].value_counts().to_dict())
pairs = []
for r in gp.itertuples():
    if r.verdict == "MISSED_LINK" and r.proposed_pairs:
        for pair in r.proposed_pairs.split(";"):
            a, _, b = pair.partition(">")
            pairs.append({"packet_id": r.packet_id, "cik": r.cik, "row_a": a, "row_b": b,
                          "usable": a.startswith("ROW-") and b.startswith("ROW-")})
pairs = pd.DataFrame(pairs)
print(f"MISSED packets={int((gp['verdict']=='MISSED_LINK').sum())} proposed pairs={len(pairs)} "
      f"with usable row ids={int(pairs['usable'].sum())}")
pairs = pairs[pairs["usable"]].reset_index(drop=True)

con = duckdb.connect()
con.register("p", pairs)
for tag, path in [("baseline", BASE), ("current", CUR)]:
    con.execute(f"""CREATE OR REPLACE TABLE h AS SELECT row_id, position_id FROM read_csv_auto('{path.as_posix()}', all_varchar=true, sample_size=-1)
                    WHERE row_id IN (SELECT row_a FROM p UNION SELECT row_b FROM p)""")
    r = con.execute("""
      SELECT COUNT(*) AS pairs,
        SUM(CASE WHEN a.position_id IS NOT NULL AND a.position_id=b.position_id THEN 1 ELSE 0 END) AS linked,
        SUM(CASE WHEN a.row_id IS NULL OR b.row_id IS NULL THEN 1 ELSE 0 END) AS rows_missing
      FROM p LEFT JOIN h a ON a.row_id=p.row_a LEFT JOIN h b ON b.row_id=p.row_b""").fetchone()
    print(f"{tag}: proposed pairs={r[0]} linked={r[1]} ({r[1]/max(r[0],1):.1%}) rows_missing={r[2]}")
