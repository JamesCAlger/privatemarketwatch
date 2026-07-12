"""Refresh the FROZEN gold frame's stored pipeline values from the (rebuilt)
production parquet -- in place, preserving every unit and _key exactly, so existing
labels stay matched. Only the per-unit `pipeline` snapshot (lien_position,
index_classification, fair_value, cost, pct_of_net_assets) is updated; sampling,
strata, pi, and ordering are untouched.

Use after a `--unified` rebuild changes derived fields (e.g. the lien overlay fix)
so the harness form shows the fresh pipeline value. Read-only on data/output.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[2]
FRAME = ROOT / "data" / "gold" / "samples" / "sample_frame_batch1.jsonl"
P = ROOT / "data" / "output" / "private_markets_holdings.parquet"

units = [json.loads(ln) for ln in FRAME.read_text().splitlines() if ln.strip()]
pos = [u for u in units if u["unit_type"] == "position"]
ciks = sorted({u["cik"] for u in pos})
cik_list = ",".join(f"'{c}'" for c in ciks)

con = duckdb.connect()
rows = con.execute(f"""
    SELECT lpad(cast(cast(cik AS BIGINT) AS VARCHAR),10,'0') AS cik, report_date,
           lower(trim(coalesce(bdc_investment_identifier,''))) AS idk,
           try_cast(fair_value AS DOUBLE) AS fair_value,
           try_cast(cost AS DOUBLE) AS cost,
           try_cast(pct_of_net_assets AS DOUBLE) AS pct_of_net_assets,
           index_classification, lien_position
    FROM read_parquet('{P.as_posix()}')
    WHERE upper(source) LIKE 'BDC%'
      AND lpad(cast(cast(cik AS BIGINT) AS VARCHAR),10,'0') IN ({cik_list})
""").fetchdf().to_dict("records")

lut: dict = defaultdict(list)
for r in rows:
    lut[(r["cik"], r["report_date"], r["idk"])].append(r)

lien_gained = matched = 0
for u in pos:
    key = (u["cik"], u.get("report_date"), (u.get("source_identifier") or "").strip().lower())
    cands = lut.get(key, [])
    if not cands:
        continue
    want_fv = (u.get("pipeline") or {}).get("fair_value")
    if len(cands) > 1 and want_fv is not None:
        cands = sorted(cands, key=lambda r: abs((r["fair_value"] or 0) - want_fv))
    r = cands[0]
    matched += 1
    pipe = u.setdefault("pipeline", {})
    before = pipe.get("lien_position")
    pipe["fair_value"] = r["fair_value"]
    pipe["cost"] = r["cost"]
    pipe["pct_of_net_assets"] = r["pct_of_net_assets"]
    pipe["index_classification"] = r["index_classification"]
    pipe["lien_position"] = r["lien_position"] or None
    if not before and pipe["lien_position"]:
        lien_gained += 1

with FRAME.open("w", encoding="ascii") as fh:
    for u in units:
        fh.write(json.dumps(u, default=str) + "\n")

print(f"[refresh] position units={len(pos)} matched_in_parquet={matched}")
print(f"[refresh] lien newly populated (None -> value): {lien_gained}")
print(f"[refresh] frame rewritten in place; _keys and sampling unchanged")
