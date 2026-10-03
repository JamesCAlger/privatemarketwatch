"""Build bounded experimental Jev packets from current flags and cached filings.

Example: python scripts/build_jev_bundles.py --rules C107 X08 --cik 1872371
    --quarter 2023-12-31 --limit 4 --out scratch/my_session/bundles

No SEC or Jev API calls. No review-ledger writes. Requires explicit output dir.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb

from pipeline import config
from pipeline.jev_bundles import RULES, SourceCache, build_bundle, digest_file, make_request


def read_inputs(flags_path: Path, holdings_path: Path, *, rules: list[str], ciks: list[str],
                quarter: str | None, row_ids: list[str], limit: int) -> tuple[list, dict]:
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='1GB'")
        con.execute("SET threads=2")
        conditions = ["rule_id IN (" + ",".join("?" for _ in rules) + ")", "source='bdc'"]
        params = [str(flags_path), *rules]
        for column, items in (("cik", ciks), ("row_id", row_ids)):
            if items:
                conditions.append(column + " IN (" + ",".join("?" for _ in items) + ")")
                params.extend(items)
        if quarter:
            conditions.append("report_date=?")
            params.append(quarter)
        query = "SELECT * FROM read_csv(?, all_varchar=true) WHERE " + " AND ".join(conditions)
        query += " ORDER BY cik, report_date DESC, rule_id, row_id LIMIT ?"
        result = con.execute(query, [*params, limit])
        columns = [c[0] for c in result.description]
        flags = [dict(zip(columns, row)) for row in result.fetchall()]
        selected_ids = sorted({f["row_id"] for f in flags if f.get("row_id")})
        matches = defaultdict(list)
        if selected_ids:
            result = con.execute("SELECT * FROM read_csv(?, all_varchar=true) WHERE row_id IN ("
                                 + ",".join("?" for _ in selected_ids) + ") LIMIT 1001", [str(holdings_path), *selected_ids])
            columns = [c[0] for c in result.description]
            rows = result.fetchall()
            if len(rows) > 1000:
                raise ValueError("Exact row join exceeds safety bound")
            for values in rows:
                row = dict(zip(columns, values))
                matches[row["row_id"]].append(row)
        return flags, matches
    finally:
        con.close()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", nargs="+", choices=sorted(RULES), default=['C107', 'X08'])
    parser.add_argument("--cik", action="append", default=[])
    parser.add_argument("--quarter")
    parser.add_argument("--row-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--flags", type=Path, default=config.ROW_VALIDATION_ISSUES_FILE)
    parser.add_argument("--holdings", type=Path, default=config.OUTPUT_DIR / "private_markets_holdings.csv")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--max-proxy-tokens", type=int, default=26000)
    args = parser.parse_args()
    if not 1 <= args.limit <= 50 or not 10 <= args.timeout_seconds <= 600:
        parser.error("limit must be 1..50 and timeout-seconds 10..600")
    if not 1000 <= args.max_proxy_tokens <= 26000:
        parser.error("max-proxy-tokens must be 1000..26000 (an estimate, not Jev's tokenizer)")
    out = args.out.resolve()
    if any(out == p.resolve() or out.is_relative_to(p.resolve()) for p in
           (config.OUTPUT_DIR, config.PROJECT_ROOT / "frontend/public/data", config.RAW_DIR)):
        parser.error("Experimental packets must be written outside production data roots")
    if out.exists() and any(out.iterdir()):
        parser.error("Output directory must be new or empty; frozen packets are not overwritten")
    import tiktoken
    tokenizer = tiktoken.get_encoding("cl100k_base")
    def timed_out():
        print("ERROR: bundle build timeout; no complete manifest was produced", flush=True)
        os._exit(124)
    timer = threading.Timer(args.timeout_seconds, timed_out)
    timer.daemon = True
    timer.start()
    started = time.monotonic()
    try:
        print("Fingerprinting current flags and holdings", flush=True)
        paths = (args.flags, args.holdings)
        stamps = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}
        provenance = {"flags_path": str(args.flags), "flags_sha256": digest_file(args.flags),
                      "holdings_path": str(args.holdings), "holdings_sha256": digest_file(args.holdings),
                      "builder_sha256": digest_file(ROOT / "pipeline/jev_bundles.py"),
                      "rule_implementation_sha256": digest_file(ROOT / "pipeline/column_validation.py")}
        flags, matches = read_inputs(args.flags, args.holdings, rules=args.rules,
                                     ciks=[c.zfill(10) for c in args.cik], quarter=args.quarter,
                                     row_ids=args.row_id, limit=args.limit)
        if not flags:
            raise ValueError("No matching current flags; no historical ordinal fallback is allowed")
        cache, records, packets = SourceCache(), [], []
        for index, flag in enumerate(flags, 1):
            print(f"Building {index}/{len(flags)} {flag['rule_id']} {flag['row_id']}", flush=True)
            bundle = build_bundle(flag, matches.get(flag.get("row_id"), []), provenance, cache=cache)
            request, proxy_tokens = None, None
            if bundle["evidence_status"]["status"] == "ready_for_model":
                request = make_request(bundle)
                proxy_tokens = len(tokenizer.encode(json.dumps(request, ensure_ascii=True), disallowed_special=()))
                if proxy_tokens > args.max_proxy_tokens:
                    bundle["evidence_status"]["status"] = "blocked"
                    bundle["evidence_status"]["blocking_reasons"].append("request_proxy_token_limit")
                    request = None
            stem = bundle["bundle_id"]
            records.append({"bundle_id": stem, "rule_id": flag["rule_id"], "row_id": flag.get("row_id"),
                            "issuer_name": bundle["output_position"].get("issuer_name"),
                            "status": bundle["evidence_status"]["status"],
                            "blocking_reasons": bundle["evidence_status"]["blocking_reasons"],
                            "candidate_count": len(bundle["source_candidates"]),
                            "proxy_input_tokens": proxy_tokens, "bundle_path": f"{stem}.bundle.json",
                            "request_path": f"{stem}.request.json" if request else None})
            packets.append((stem, bundle, request))
        if any((p.stat().st_size, p.stat().st_mtime_ns) != stamps[p] for p in paths):
            raise RuntimeError("Input artifacts changed during build; no packets written")
        out.mkdir(parents=True, exist_ok=True)
        for stem, bundle, request in packets:
            write_json(out / f"{stem}.bundle.json", bundle)
            if request:
                write_json(out / f"{stem}.request.json", request)
        for record in records:
            record["bundle_sha256"] = digest_file(out / record["bundle_path"])
            if record["request_path"]:
                record["request_sha256"] = digest_file(out / record["request_path"])
        manifest = {"schema_version": "jev-bundle-manifest.v1", "provenance": provenance, "cases": records,
                    "status_counts": dict(Counter(r["status"] for r in records)),
                    "runtime_seconds": round(time.monotonic() - started, 3),
                    "tokenizer": "cl100k_base proxy, not Jev tokenizer; provider limit not verified",
                    "api_calls": 0, "automatic_adjudications": 0}
        write_json(out / "manifest.json", manifest)
        print(json.dumps({"out": str(out), "status_counts": manifest["status_counts"],
                          "seconds": manifest["runtime_seconds"]}, ensure_ascii=True), flush=True)
    finally:
        timer.cancel()


if __name__ == "__main__":
    main()
