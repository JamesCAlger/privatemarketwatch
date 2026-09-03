"""Score match-gold verdicts into gold_set.csv + per-tier precision.

Reads worker verdict JSONs (utf-8-sig tolerant), validates against
pipeline.match_verdict_leaf, joins edge verdicts to blinded tiers from
packets_meta sidecars. Invalid/missing verdicts are surfaced, never dropped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.match_verdict_leaf import validate_match_verdict  # noqa: E402


# Exact column order for gold_set.csv output
GOLD_COLS = [
    "packet_id", "packet_type", "stratum", "unit", "edge_index",
    "tier", "verdict", "confidence", "valid", "audit_flag"
]


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _audit_pick(packet_id: str) -> bool:
    return int(hashlib.md5(packet_id.encode()).hexdigest()[:8], 16) % 10 == 0


def score_batch(batch_dir: Path) -> dict:
    batch_dir = Path(batch_dir)
    worklist = pd.read_csv(batch_dir / "worklist.csv")
    gold_rows, invalid, missing = [], [], []

    for wl in worklist.itertuples(index=False):   # <=600 rows, loop is fine
        pid = wl.packet_id
        meta = json.loads((batch_dir / "packets_meta" / f"{pid}.json")
                          .read_text(encoding="utf-8"))
        vpath = batch_dir / "verdicts" / f"{pid}.json"
        if not vpath.exists():
            missing.append(pid)
            continue
        doc = json.loads(vpath.read_text(encoding="utf-8-sig"))
        expected = [e["edge_index"] for e in meta.get("edges", [])]
        errs = validate_match_verdict(doc, expected_edges=expected)
        valid = not errs
        if errs:
            invalid.append({"packet_id": pid, "errors": errs})
        tier_of = {e["edge_index"]: e.get("match_method", "")
                   for e in meta.get("edges", [])}
        base = {"packet_id": pid, "packet_type": meta["packet_type"],
                "stratum": meta["stratum"], "valid": valid,
                "audit_flag": _audit_pick(pid)}
        for ev in (doc.get("edge_verdicts") or []):
            gold_rows.append({**base, "unit": "edge",
                              "edge_index": ev.get("edge_index"),
                              "tier": tier_of.get(ev.get("edge_index"), ""),
                              "verdict": ev.get("verdict"),
                              "confidence": doc.get("confidence")})
        gold_rows.append({**base, "unit": "packet", "edge_index": None,
                          "tier": "", "verdict": doc.get("verdict"),
                          "confidence": doc.get("confidence")})

    # Construct DataFrame with explicit columns to handle empty gold_rows gracefully
    gold = pd.DataFrame(gold_rows, columns=GOLD_COLS)
    if not gold.empty:
        gold = gold.sort_values(
            ["packet_id", "unit", "edge_index"], na_position="last")
    gold.to_csv(batch_dir / "gold_set.csv", index=False)

    edges = gold[(gold["unit"] == "edge") & gold["valid"]]
    prec_rows = []
    if not edges.empty:
        for tier, grp in edges.groupby("tier"):
            k = int((grp["verdict"] == "CONFIRMED").sum())
            w = int((grp["verdict"] == "WRONG").sum())
            u = int((grp["verdict"] == "UNCERTAIN").sum())
            n = k + w
            p = k / n if n else 0.0
            lo, hi = wilson_interval(k, n)
            prec_rows.append({"tier": tier, "n_confirmed": k, "n_wrong": w,
                              "n_uncertain": u, "precision": p,
                              "wilson_lo": lo, "wilson_hi": hi})
    prec_df = pd.DataFrame(prec_rows)
    if not prec_df.empty:
        prec_df = prec_df.sort_values("tier")
    prec_df.to_csv(batch_dir / "precision_by_tier.csv", index=False)

    audit = gold[gold["audit_flag"] & (gold["unit"] == "packet")]
    packet_rows = gold[gold["unit"] == "packet"]
    if not packet_rows.empty:
        for (ptype, verdict), grp in packet_rows.groupby(
                ["packet_type", "verdict"]):
            if not grp["audit_flag"].any():
                fallback = grp.assign(_o=grp["packet_id"].map(
                    lambda x: hashlib.md5(x.encode()).hexdigest()))
                fallback = fallback.sort_values("_o").head(1).drop(columns="_o")
                audit = pd.concat([audit, fallback])
    if not audit.empty:
        audit = audit.sort_values("packet_id")
    audit.to_csv(batch_dir / "audit_slice.csv", index=False)

    stats = {"n_verdicts": int(worklist.shape[0] - len(missing)),
             "n_invalid": len(invalid), "n_missing": len(missing)}
    lines = ["# Match-gold scoring summary", "",
             f"- verdicts: {stats['n_verdicts']}",
             f"- invalid: {stats['n_invalid']}",
             f"- missing: {stats['n_missing']}", ""]
    for item in invalid:
        lines.append(f"- INVALID {item['packet_id']}: {'; '.join(item['errors'])}")
    for pid in missing:
        lines.append(f"- MISSING {pid}")
    (batch_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-dir", required=True)
    args = ap.parse_args()
    print(score_batch(Path(args.batch_dir)))


if __name__ == "__main__":
    main()
