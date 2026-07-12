"""CLI over pipeline.agent_data_query: the B2 agent's read-only, cik-scoped window into the
EXTRACTED data (the extracted-data analog of evidence_cli's filing window).

    python scripts/review_agent/data_query_cli.py --cik 1377936 schema
    python scripts/review_agent/data_query_cli.py --cik 1377936 query --sql \
        "SELECT report_date, count(*), round(sum(fair_value),0) FROM holdings GROUP BY 1 ORDER BY 1"

Tables (each pre-filtered to the cik): holdings, staging, fund_financials, conservation.
Read-only, single SELECT, no file/network access from agent SQL, results row-capped.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.agent_data_query import query, describe, default_sources  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only cik-scoped query over extracted data.")
    ap.add_argument("--cik", required=True)
    ap.add_argument("cmd", choices=["schema", "query"])
    ap.add_argument("--sql", default="")
    ap.add_argument("--row-cap", type=int, default=500)
    ap.add_argument("--holdings", default=None,
                    help="override the `holdings` table source (e.g. a corrected trial file, "
                         "to investigate the residual that REMAINS after rules so far)")
    args = ap.parse_args(argv)

    src = None
    if args.holdings:
        src = default_sources()
        src["holdings"] = args.holdings

    if args.cmd == "schema":
        print(json.dumps(describe(cik=args.cik, sources=src), indent=2, default=str))
        return 0
    out = query(args.sql, cik=args.cik, sources=src, row_cap=args.row_cap)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
