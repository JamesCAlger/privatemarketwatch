"""Download the SEC companyfacts JSON for named funds into a holding folder.

NETWORK: calls SEC EDGAR (one request per fund). Run only when the owner has asked for it.

    python scripts/download_companyfacts.py --ciks 0001803498 0001812554 --expect 2026-06-30

Writes ``data/raw/filings/quarter_downloads/companyfacts_<expect>/<cik10>.json`` and reports, per
fund, how many facts end on the expected date and how the file compares with the one in the live
cache (``data/raw/companyfacts_cache``). The live cache is not touched: every build reads it, so
replacing a fund's file there is a separate, deliberate copy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ends(data: dict) -> dict[str, int]:
    """fact count by period end date."""
    counts: dict[str, int] = {}
    for taxonomy in (data.get("facts") or {}).values():
        for concept in taxonomy.values():
            for facts in (concept.get("units") or {}).values():
                for fact in facts:
                    counts[fact.get("end", "")] = counts.get(fact.get("end", ""), 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ciks", nargs="+", required=True)
    parser.add_argument("--expect", required=True, help="period end the new file should carry, YYYY-MM-DD")
    args = parser.parse_args(argv)

    from pipeline.config import BDC_HTML_CACHE_DIR, COMPANYFACTS_CACHE_DIR
    from pipeline.edgar_client import EdgarClient

    folder = BDC_HTML_CACHE_DIR.parent / "quarter_downloads" / ("companyfacts_" + args.expect)
    folder.mkdir(parents=True, exist_ok=True)
    client = EdgarClient()
    missing = 0
    for cik in sorted({"".join(ch for ch in c if ch.isdigit()).zfill(10) for c in args.ciks}):
        data = client.get_json("https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json" % cik)
        target = folder / (cik + ".json")
        target.write_text(json.dumps(data), encoding="utf-8")
        new = _ends(data)
        live = COMPANYFACTS_CACHE_DIR / (cik + ".json")
        old = _ends(json.loads(live.read_text(encoding="utf-8"))) if live.exists() else {}
        missing += 0 if new.get(args.expect) else 1
        print("%s %s | facts ending %s: %d | facts in all: %d (live cache: %d, latest end there %s) -> %s" % (
            cik, data.get("entityName", ""), args.expect, new.get(args.expect, 0), sum(new.values()), sum(old.values()),
            max((d for d in old if d <= "2030"), default=""), target))
    print("funds without facts for %s: %d" % (args.expect, missing))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
