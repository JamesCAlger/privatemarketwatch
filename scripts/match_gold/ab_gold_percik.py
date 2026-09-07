"""Per-CIK A/B of the position matcher against the match-gold verdicts.

For every CIK that has gold pairs (mg3 + mg4_contested edge verdicts and MISSED
proposed links), run the matcher twice on that CIK's rows -- A: contested flag
OFF (prior production), B: contested flag ON with the current code -- and report
which gold pairs end up linked (same position_id) under each.

Read-only on data/output: matches go to a scratch file, the edge-ledger writer is
stubbed, the registry is not used.

Usage:
    python scripts/match_gold/ab_gold_percik.py --out scratch/<session>/ab_new
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import pipeline.position_matching as pm  # noqa: E402

GOLD_OUT = REPO / "scripts/match_gold/chain_experiments/out"
HOLD = REPO / "data/output/private_markets_holdings.csv"
RAW = REPO / "data/output/bdc_holdings.csv"


def load_gold_pairs(batches: list[str]) -> pd.DataFrame:
    rows = []
    for b in batches:
        ge = pd.read_csv(GOLD_OUT / b / "gold_edges.csv", dtype=str).fillna("")
        for r in ge.itertuples():
            if r.verdict in ("CONFIRMED", "WRONG") and r.b_row_id and r.e_row_id:
                rows.append({"batch": b, "kind": r.verdict, "tier": r.tier, "cik": r.cik,
                             "row_a": r.b_row_id, "row_b": r.e_row_id})
        gp = pd.read_csv(GOLD_OUT / b / "gold_packets.csv", dtype=str).fillna("")
        for r in gp.itertuples():
            if r.verdict == "MISSED_LINK" and r.proposed_pairs:
                for pair in r.proposed_pairs.split(";"):
                    a, _, bb = pair.partition(">")
                    if a.startswith("ROW-") and bb.startswith("ROW-"):
                        rows.append({"batch": b, "kind": "MISSED", "tier": "", "cik": r.cik,
                                     "row_a": a, "row_b": bb})
    df = pd.DataFrame(rows).drop_duplicates(subset=["row_a", "row_b"])
    return df


def run_variant(u: pd.DataFrame, raw: pd.DataFrame, flag: bool, tmp: Path) -> dict[str, str]:
    matches = pm.match_positions(unified_df=u, bdc_raw_df=raw, output_file=tmp,
                                 contested_assignment=flag)
    out, _ = pm.assign_position_ids(u.copy(), matches, contested_assignment=flag)
    return dict(zip(out["row_id"], out["position_id"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--batches", default="mg3,mg4_contested")
    ap.add_argument("--limit-ciks", type=int, default=0)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pm._write_position_id_edges = lambda edges: None   # never touch data/output

    gold = load_gold_pairs(args.batches.split(","))
    ciks = sorted(gold["cik"].unique())
    if args.limit_ciks:
        ciks = ciks[: args.limit_ciks]
    print(f"gold pairs={len(gold)} kinds={gold['kind'].value_counts().to_dict()} ciks={len(ciks)}", flush=True)
    cik_list = ",".join(f"'{c}'" for c in ciks)

    con = duckdb.connect()
    t0 = time.time()
    u_all = con.execute(f"SELECT * FROM read_csv_auto('{HOLD.as_posix()}', all_varchar=true, sample_size=-1) "
                        f"WHERE cik IN ({cik_list})").df()
    raw_all = con.execute(f"SELECT * FROM read_csv_auto('{RAW.as_posix()}', all_varchar=true, sample_size=-1) "
                          f"WHERE LPAD(CAST(cik AS VARCHAR), 10, '0') IN ({cik_list})").df()
    raw_all["cik"] = raw_all["cik"].astype(str).str.zfill(10)
    print(f"loaded unified={len(u_all)} raw={len(raw_all)} in {time.time()-t0:.0f}s", flush=True)

    tmp = args.out / "tmp_matches.csv"
    results = []
    for i, cik in enumerate(ciks, 1):
        u = u_all[u_all["cik"] == cik].reset_index(drop=True)
        raw = raw_all[raw_all["cik"] == cik].reset_index(drop=True)
        g = gold[gold["cik"] == cik]
        t1 = time.time()
        pid_a = run_variant(u, raw, False, tmp)
        pid_b = run_variant(u, raw, True, tmp)
        for r in g.itertuples():
            la = pid_a.get(r.row_a) is not None and pid_a.get(r.row_a) == pid_a.get(r.row_b)
            lb = pid_b.get(r.row_a) is not None and pid_b.get(r.row_a) == pid_b.get(r.row_b)
            results.append({"batch": r.batch, "kind": r.kind, "tier": r.tier, "cik": cik,
                            "row_a": r.row_a, "row_b": r.row_b, "linked_A": la, "linked_B": lb,
                            "present": r.row_a in pid_a and r.row_b in pid_a})
        print(f"[{i}/{len(ciks)}] {cik} rows={len(u)} raw={len(raw)} pairs={len(g)} {time.time()-t1:.0f}s", flush=True)
        pd.DataFrame(results).to_csv(args.out / "ab_pairs.csv", index=False)

    res = pd.DataFrame(results)
    lines = ["# Per-CIK A/B: contested OFF (A) vs ON, current code (B)", "",
             f"batches: {args.batches}; CIKs: {len(ciks)}; pairs: {len(res)} (present in holdings: {int(res['present'].sum())})", "",
             "| kind | n | linked A | linked B |", "|---|---|---|---|"]
    for kind in ["WRONG", "CONFIRMED", "MISSED"]:
        s = res[res["kind"] == kind]
        lines.append(f"| {kind} | {len(s)} | {int(s['linked_A'].sum())} | {int(s['linked_B'].sum())} |")
    w = res[res["kind"] == "WRONG"]
    c = res[res["kind"] == "CONFIRMED"]
    m = res[res["kind"] == "MISSED"]
    lines += ["",
              f"WRONG broken by B: {int((w['linked_A'] & ~w['linked_B']).sum())}",
              f"WRONG newly linked by B: {int((~w['linked_A'] & w['linked_B']).sum())}",
              f"CONFIRMED lost by B: {int((c['linked_A'] & ~c['linked_B']).sum())}",
              f"CONFIRMED gained by B: {int((~c['linked_A'] & c['linked_B']).sum())}",
              f"MISSED recovered by B: {int((~m['linked_A'] & m['linked_B']).sum())}",
              f"MISSED lost by B: {int((m['linked_A'] & ~m['linked_B']).sum())}",
              "",
              "WRONG still linked in B, by tier: " + json.dumps(Counter(w[w['linked_B']]['tier']).most_common()),
              "CONFIRMED lost by B, by tier: " + json.dumps(Counter(c[c['linked_A'] & ~c['linked_B']]['tier']).most_common()),
              "",
              "## per batch",
              "| batch | kind | n | linked A | linked B |", "|---|---|---|---|---|"]
    for (b, kind), s in res.groupby(["batch", "kind"]):
        lines.append(f"| {b} | {kind} | {len(s)} | {int(s['linked_A'].sum())} | {int(s['linked_B'].sum())} |")
    (args.out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
