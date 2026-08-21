"""Replay the B3 value gate over a directory of correction leaves (cache-only).

Pre-gate for authored/archived B2 leaves and an audit tool for live ones: for each
leaf, slice production unified holdings to the leaf's CIK (DuckDB over the parquet --
no full-frame load), build the trial frame with the SCOPED production application path
(``apply_scoped``), and run ``gate_value_packet`` -- including the round-4
``magnitude_plausible`` predicate. Read-only on production; nothing is promoted.

Two modes:
 - default (replay): baseline = current production slice; trial = apply_scoped(base).
   Correct for leaves NOT currently applied in production (archives, staged
   re-authors). A live leaf replayed this way would double-apply -- use --stats-only.
 - --stats-only: no replay; report the magnitude deviation of the CURRENT production
   target-quarter statistics vs the fund's off-target norm for the leaf's touched
   fields. For live (already-applied) leaves this measures whether the promoted state
   itself sits inside the magnitude band the round-4 predicate enforces.

Usage:
  python -m scripts.agent_b2.replay_gate --corrections-dir data/output/agent_b2/corrections_archive/q4b2exp_v3_magnitude_pull
  python -m scripts.agent_b2.replay_gate --corrections-dir data/overrides/agent_b2_corrections --stats-only

ASCII-only output.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from pipeline import config
from scripts.agent_b2 import run_remediation as rr

DEFAULT_HOLDINGS = config.UNIFIED_HOLDINGS_PARQUET_FILE


def load_leaves(corrections_dir: Path) -> list[tuple[Path, dict]]:
    leaves = []
    for p in sorted(Path(corrections_dir).rglob("*.json")):
        try:
            leaf = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as e:
            leaves.append((p, {"_load_error": str(e)}))
            continue
        if isinstance(leaf, dict) and leaf.get("cik"):
            leaves.append((p, leaf))
    return leaves


def slice_cik(holdings_path: Path, cik: str, con=None) -> pd.DataFrame:
    """Per-CIK slice of unified holdings via DuckDB (parquet or csv)."""
    con = con or duckdb.connect()
    src = str(holdings_path).replace("'", "''")
    reader = ("read_parquet" if str(holdings_path).endswith(".parquet")
              else "read_csv_auto")
    target = str(cik).lstrip("0")
    return con.execute(
        f"SELECT * FROM {reader}('{src}') "
        f"WHERE ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') = ?",
        [target]).fetchdf()


def resolve_target_quarter(leaf: dict, df: pd.DataFrame) -> str:
    quarters = [str(q) for q in (leaf.get("scope") or {}).get("quarters", [])
                if q and str(q) != "all"]
    if quarters:
        return sorted(quarters)[-1]
    rd = str((leaf.get("template") or {}).get("report_date") or "")
    if rd:
        return rd
    if "report_date" in df.columns and len(df):
        return str(df["report_date"].astype(str).max())
    return ""


def magnitude_stats(df: pd.DataFrame, leaf: dict, target_quarter: str) -> list[dict]:
    """Per touched field: deviation (log10) of the CURRENT target-quarter statistic vs
    the fund's off-target norm. No replay -- audits the frame as it stands."""
    out = []
    tq = str(target_quarter)

    def _one(label, stats):
        off = [v for q, v in stats.items() if q != tq and v > 0]
        if len(off) < rr._MAGNITUDE_MIN_NORM_QUARTERS:
            out.append({"leg": label, "status": "no_norm", "n_off_quarters": len(off)})
            return
        norm = float(statistics.median(off))
        t = stats.get(tq)
        if not t or norm <= 0:
            out.append({"leg": label, "status": "no_target_values"})
            return
        dev = abs(math.log10(t / norm))
        out.append({"leg": label, "status": "ok", "target_stat": round(t, 6),
                    "fund_norm": round(norm, 6), "dev_log10": round(dev, 3),
                    "in_band": dev <= rr._MAGNITUDE_LOG10_TOL})

    fields = rr._magnitude_fields(leaf)
    for f in fields:
        _one(f"field {f}", rr._quarter_field_means(df, f))
    if "principal_amount" in fields or "fair_value" in fields:
        _one("principal/FV ratio", rr._quarter_ratio_medians(df))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replay the B3 value gate over correction leaves.")
    ap.add_argument("--corrections-dir", type=Path, required=True)
    ap.add_argument("--holdings", type=Path, default=DEFAULT_HOLDINGS)
    ap.add_argument("--stats-only", action="store_true",
                    help="No replay: magnitude stats of the CURRENT frame (for live leaves).")
    ap.add_argument("--limit", type=int, default=200, help="Max leaves to process.")
    ap.add_argument("--out", type=Path, default=None,
                    help="Also write the results JSON here (utf-8, no BOM) -- used for "
                         "the mandatory post-promotion audit artifact "
                         "replay_live_stats_<batch_id>.json.")
    ap.add_argument("--readju-worklist", type=Path, default=None,
                    help="Append wrong-diagnosis gate refusals to this re-adjudication "
                         "worklist (default: no writes; preserves read-only behavior).")
    ap.add_argument("--batch-id", default="",
                    help="Batch id recorded on re-adjudication worklist rows.")
    args = ap.parse_args(argv)

    leaves = load_leaves(args.corrections_dir)[: args.limit]
    print(f"[replay_gate] {len(leaves)} leaf(s) from {args.corrections_dir}")
    con = duckdb.connect()
    results = []
    leaf_map = {str(path.relative_to(args.corrections_dir)): leaf
                for path, leaf in leaves if "_load_error" not in leaf}
    for i, (path, leaf) in enumerate(leaves, 1):
        rec: dict = {"leaf": str(path.relative_to(args.corrections_dir))}
        if "_load_error" in leaf:
            rec.update(status="load_error", error=leaf["_load_error"])
            results.append(rec)
            continue
        cik = str(leaf.get("cik"))
        rec.update(cik=cik, fix_class=leaf.get("fix_class"))
        base = slice_cik(args.holdings, cik, con=con)
        tq = resolve_target_quarter(leaf, base)
        rec["target_quarter"] = tq
        print(f"[replay_gate] {i}/{len(leaves)} cik={cik} fix_class={leaf.get('fix_class')} "
              f"rows={len(base)} target={tq}")
        if not len(base):
            rec.update(status="no_holdings_rows")
            results.append(rec)
            continue
        if args.stats_only:
            rec.update(status="stats", magnitude=magnitude_stats(base, leaf, tq))
        else:
            from pipeline.agent_b2_appliers import apply_scoped
            trial, _ = apply_scoped(base, leaf)
            res = rr.gate_value_packet(cik=cik, target_quarter=tq, baseline_df=base,
                                       trial_df=trial, correction=leaf)
            rec.update(status="gated", verdict=res["verdict"], checks=res["checks"],
                       reasons=res["reasons"])
        results.append(rec)
    print(json.dumps(results, indent=2, default=str))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"[replay_gate] wrote {args.out}")
    if args.readju_worklist is not None and not args.stats_only:
        entries = []
        for r in results:
            vres = {"verdict": r.get("verdict"), "checks": r.get("checks", {}),
                    "reasons": r.get("reasons", [])}
            if r.get("status") == "gated" and rr.is_diagnosis_refusal(vres):
                reasons = r.get("reasons") or []
                entries.append({
                    "cik": r.get("cik", ""), "fix_class": r.get("fix_class", ""),
                    "source_review_ids": ";".join(
                        (leaf_map.get(r["leaf"], {}).get("source_review_ids") or [])),
                    "batch_id": args.batch_id,
                    "gated_utc": datetime.now(timezone.utc).isoformat(),
                    "reason": str(reasons[0]) if reasons else "magnitude_plausible false"})
        n = rr.append_readjudication(entries, path=args.readju_worklist)
        print(f"[replay_gate] {n} re-adjudication worklist row(s) appended")
    n_fail = sum(1 for r in results if r.get("verdict") == "FAIL")
    n_out = sum(1 for r in results
                for m in (r.get("magnitude") or []) if m.get("in_band") is False)
    print(f"[replay_gate] done: {len(results)} leaf(s), {n_fail} gate FAIL, "
          f"{n_out} magnitude leg(s) out of band")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
