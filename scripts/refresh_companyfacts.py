"""Refresh companyfacts cache entries for CIKs whose anchors lag a target quarter.

THE ONLY NETWORKED SCRIPT in the quarter-pass toolchain, and it is EXPLICITLY
operator-invoked: neither the pass nor the preflight ever calls it. The preflight's
anchor_assessability FAIL prints the exact invocation with the lagging CIKs.

Mechanism: the companyfacts fetch path has a 7-day disk cache
(pipeline.validate_html_template._fetch_companyfacts), so a stale-but-recent cache
file blocks a refresh. This script ARCHIVES the existing cache file to
``data/raw/companyfacts_cache/_archive/<UTC timestamp>/`` (never deletes -- the
leading underscore keeps it out of by-cik scans) and re-fetches through the
existing EdgarClient (built-in 10 req/s limiter; one shared client). Replaces the
manual cache-surgery hack the 2026-07-23 q1shakedown needed.

Usage (operator terminal):
  python -m scripts.refresh_companyfacts --quarter 2026-03-31 --ciks 0001377936 ...
  python -m scripts.refresh_companyfacts --quarter 2026-03-31 --cohort [--dry-run]

Exit 0 always (report-only semantics); the report states which CIKs now carry a
fact period ending at the target quarter so SEC lag is visible. ASCII-only.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402

logger = logging.getLogger(__name__)

CACHE_DIR = config.DATA_DIR / "raw" / "companyfacts_cache"


def _quarter_covered(facts: dict, quarter: str) -> bool:
    """True when any us-gaap fact unit carries a period ending at ``quarter``."""
    for concept in (facts.get("facts") or {}).get("us-gaap", {}).values():
        for unit_rows in (concept.get("units") or {}).values():
            for row in unit_rows:
                if row.get("end") == quarter:
                    return True
    return False


def refresh(ciks: list[str], quarter: str, *, client=None, cache_dir: Path = CACHE_DIR,
            dry_run: bool = False, fetch=None) -> list[dict]:
    """Archive-then-refetch each CIK's companyfacts; report quarter coverage.

    ``client``/``fetch`` are injectable for tests; the default fetch is the
    production 7-day-cached path (bypassed here because the file was archived)."""
    if fetch is None:
        from pipeline.validate_html_template import _fetch_companyfacts as fetch
    if client is None and not dry_run:
        from pipeline.edgar_client import EdgarClient
        client = EdgarClient()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = cache_dir / "_archive" / stamp
    results = []
    for cik in ciks:
        cik10 = str(cik).zfill(10)
        cache = cache_dir / f"{cik10}.json"
        rec = {"cik": cik10, "archived": False, "fetched": False,
               "quarter_covered": None}
        if dry_run:
            rec["dry_run"] = True
            rec["would_archive"] = cache.exists()
            results.append(rec)
            logger.info("[dry-run] %s: would archive=%s then fetch", cik10, cache.exists())
            continue
        if cache.exists():
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(cache), str(archive_dir / cache.name))
            rec["archived"] = True
        facts = fetch(cik10, client)
        rec["fetched"] = bool(facts)
        rec["quarter_covered"] = _quarter_covered(facts, quarter) if facts else False
        results.append(rec)
        logger.info("%s: archived=%s fetched=%s quarter_%s=%s", cik10, rec["archived"],
                    rec["fetched"], quarter, rec["quarter_covered"])
    return results


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Archive + re-fetch companyfacts cache "
                                             "entries (operator-invoked; network).")
    ap.add_argument("--quarter", required=True, help="target report_date YYYY-MM-DD")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--ciks", nargs="+", help="explicit CIK list")
    grp.add_argument("--cohort", action="store_true",
                     help="refresh every wrapper-cohort CIK")
    ap.add_argument("--dry-run", action="store_true", help="report only; no moves/fetches")
    args = ap.parse_args(argv)

    if args.cohort:
        from pipeline.quarter_acceptance import load_cohort
        ciks = sorted(load_cohort())
    else:
        ciks = args.ciks
    results = refresh(ciks, args.quarter, dry_run=args.dry_run)
    n_cov = sum(1 for r in results if r.get("quarter_covered"))
    logger.info("refresh done: %d cik(s), %d now cover %s (remainder = SEC lag, "
                "quarter stays skip/NOT_ASSESSABLE for them)",
                len(results), n_cov, args.quarter)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
