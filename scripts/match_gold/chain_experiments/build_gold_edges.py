"""Flatten mg3 packets + verdicts into edge-level and packet-level CSVs.

Read-only over data/output; writes only to the scratch session dir.
535 packets -- bounded.
"""
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BATCH = sys.argv[1] if len(sys.argv) > 1 else "mg3"
G = REPO / "data/output/match_quality/gold" / BATCH
OUT = Path(__file__).resolve().parent / "out" / BATCH
OUT.mkdir(parents=True, exist_ok=True)

ROW_FIELDS = ["row_id", "report_date", "accession_number", "issuer_name",
              "bdc_investment_identifier", "instrument_description", "maturity_date",
              "basis_spread", "interest_rate", "principal_amount", "fair_value"]

gold = list(csv.DictReader(open(G / "gold_set.csv", encoding="utf-8")))
edges_out, packets_out, cands_out = [], [], []
n_pk = 0
for pk_path in sorted((G / "packets").glob("*.json")):
    pk = json.load(open(pk_path, encoding="utf-8"))
    pid = pk["packet_id"]
    vpath = G / "verdicts" / f"{pid}.json"
    if not vpath.exists():
        continue
    v = json.load(open(vpath, encoding="utf-8"))
    n_pk += 1
    rows = {r["row_id"]: r for r in pk.get("rows", [])}
    cands = {r["row_id"]: r for r in pk.get("candidate_rows", [])}
    stratum = next((g["stratum"] for g in gold if g["packet_id"] == pid), "")
    rat = (v.get("rationale") or "").replace("\n", " ")
    packets_out.append({
        "packet_id": pid, "packet_type": pk["packet_type"], "stratum": stratum,
        "cik": pk["cik"], "verdict": v["verdict"], "confidence": v.get("confidence"),
        "n_rows": len(rows), "n_candidates": len(cands), "n_edges": len(pk.get("edges", [])),
        "n_proposed": len(v.get("proposed_links", [])),
        "proposed_pairs": ";".join(f"{p.get('row_id_a')}>{p.get('row_id_b')}"
                                    for p in v.get("proposed_links", [])),
        "rationale": rat,
    })
    ev = {e["edge_index"]: e["verdict"] for e in v.get("edge_verdicts", [])}
    for e in pk.get("edges", []):
        b, en = rows.get(e["begin_row_id"], {}), rows.get(e["end_row_id"], {})
        rec = {"packet_id": pid, "stratum": stratum, "cik": pk["cik"],
               "edge_index": e["edge_index"], "verdict": ev.get(e["edge_index"], ""),
               "tier": next((g["tier"] for g in gold if g["packet_id"] == pid
                             and g["unit"] == "edge"
                             and g["edge_index"] not in ("", None)
                             and float(g["edge_index"]) == float(e["edge_index"])), ""),
               "rationale": rat}
        for f in ROW_FIELDS:
            rec["b_" + f] = b.get(f)
            rec["e_" + f] = en.get(f)
        edges_out.append(rec)
    for rid, r in list(rows.items()) + list(cands.items()):
        cands_out.append({"packet_id": pid, "stratum": stratum, "cik": pk["cik"],
                          "role": "row" if rid in rows else "candidate",
                          **{f: r.get(f) for f in ROW_FIELDS}})

EDGE_COLS = (["packet_id", "stratum", "cik", "edge_index", "verdict", "tier", "rationale"]
             + [p + f for f in ROW_FIELDS for p in ("b_", "e_")])
for name, data, cols in [("gold_edges.csv", edges_out, EDGE_COLS),
                         ("gold_packets.csv", packets_out, None),
                         ("gold_rows.csv", cands_out, None)]:
    fieldnames = list(data[0].keys()) if data else cols
    with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader(); w.writerows(data)
    print(name, len(data))
print("packets with verdicts:", n_pk)
