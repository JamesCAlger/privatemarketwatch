"""Fetch fresh companyfacts for CIKs whose anchors lag a target quarter.

THE ONLY NETWORKED SCRIPT in the quarter-pass toolchain, and it is EXPLICITLY
operator-invoked: neither the pass nor the preflight ever calls it. The preflight's
anchor_assessability FAIL prints the exact invocation with the lagging CIKs.

Mechanism (2026-11-10, companyfacts snapshot store): each CIK is fetched through
the existing EdgarClient (built-in 10 req/s limiter; one shared client) and stored
as a new immutable snapshot under ``data/raw/companyfacts_snapshots/`` (source
api_download). The published pin is NEVER moved, so builds keep reading the
pinned version until the owner promotes a pin. ``--candidate-pin <file>`` also
writes a candidate pin (published pin + the fetched CIKs) for a sandbox build via
``PM_COMPANYFACTS_PIN``. The legacy ``data/raw/companyfacts_cache`` is not touched.

Usage (operator terminal):
  python -m scripts.refresh_companyfacts --quarter 2026-03-31 --ciks 0001377936 ...
  python -m scripts.refresh_companyfacts --quarter 2026-03-31 --cohort [--dry-run]
  python -m scripts.refresh_companyfacts --quarter 2026-06-30 --ciks ... --candidate-pin scratch/x/pin.json

Exit 0 always (report-only semantics); the report states which CIKs now carry a
fact period ending at the target quarter so SEC lag is visible. ASCII-only.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import companyfacts_store as store  # noqa: E402

logger = logging.getLogger(__name__)

API_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json"


def _quarter_covered(facts: dict, quarter: str) -> bool:
    """True when any us-gaap fact unit carries a period ending at ``quarter``."""
    for concept in (facts.get("facts") or {}).get("us-gaap", {}).values():
        for unit_rows in (concept.get("units") or {}).values():
            for row in unit_rows:
                if row.get("end") == quarter:
                    return True
    return False


def _api_fetch(cik10: str, client) -> dict:
    """Direct API fetch (bypasses the pinned snapshot that _fetch_companyfacts returns)."""
    try:
        return client.get_json(API_URL % cik10) or {}
    except Exception as exc:  # report-only: a failed fund stays visible in the output
        logger.warning("%s: fetch failed: %s", cik10, exc)
        return {}


def refresh(ciks: list[str], quarter: str, *, client=None, dry_run: bool = False,
            fetch=None, candidate_pin: Path | None = None) -> list[dict]:
    """Fetch each CIK, store it as a new snapshot, report quarter coverage.

    ``client``/``fetch`` are injectable for tests. Never writes the published pin."""
    if fetch is None:
        fetch = _api_fetch
    if client is None and not dry_run:
        from pipeline.edgar_client import EdgarClient
        client = EdgarClient()
    results = []
    repins: dict[str, str] = {}
    for cik in ciks:
        cik10 = store.cik10(cik)
        pinned = store.companyfacts_path(cik10)
        rec = {"cik": cik10, "fetched": False, "snapshot": None, "new_snapshot": False,
               "quarter_covered": None,
               "pinned_quarter_covered": (_quarter_covered(store.load_companyfacts(cik10), quarter)
                                          if pinned is not None else None)}
        if dry_run:
            rec["dry_run"] = True
            results.append(rec)
            logger.info("[dry-run] %s: would fetch and store a snapshot (pinned=%s)",
                        cik10, pinned is not None)
            continue
        facts = fetch(cik10, client)
        rec["fetched"] = bool(facts)
        rec["quarter_covered"] = _quarter_covered(facts, quarter) if facts else False
        if facts:
            row, created = store.add_snapshot(cik10, json.dumps(facts).encode("utf-8"),
                                              source="api_download")
            rec["snapshot"], rec["new_snapshot"] = row["path"], created
            repins[cik10] = row["path"]
        results.append(rec)
        logger.info("%s: fetched=%s snapshot=%s new=%s quarter_%s=%s (pinned version: %s)",
                    cik10, rec["fetched"], rec["snapshot"], rec["new_snapshot"], quarter,
                    rec["quarter_covered"], rec["pinned_quarter_covered"])
    if candidate_pin is not None and repins and not dry_run:
        store.write_candidate_pin(candidate_pin, repins, promoted_by="scripts/refresh_companyfacts.py",
                                  note="candidate: refreshed for " + quarter)
        logger.info("candidate pin written: %s (%d CIK(s) re-pinned; published pin unchanged)",
                    candidate_pin, len(repins))
    return results


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Fetch companyfacts into the snapshot store "
                                             "(operator-invoked; network). Never moves the published pin.")
    ap.add_argument("--quarter", required=True, help="target report_date YYYY-MM-DD")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--ciks", nargs="+", help="explicit CIK list")
    grp.add_argument("--cohort", action="store_true",
                     help="refresh every wrapper-cohort CIK")
    ap.add_argument("--candidate-pin", type=Path, default=None,
                    help="also write a candidate pin file (published pin + fetched CIKs)")
    ap.add_argument("--dry-run", action="store_true", help="report only; no fetches")
    args = ap.parse_args(argv)

    if args.cohort:
        from pipeline.quarter_acceptance import load_cohort
        ciks = sorted(load_cohort())
    else:
        ciks = args.ciks
    results = refresh(ciks, args.quarter, dry_run=args.dry_run, candidate_pin=args.candidate_pin)
    n_cov = sum(1 for r in results if r.get("quarter_covered"))
    logger.info("refresh done: %d cik(s), %d now cover %s in the fetched version (remainder = SEC lag). "
                "Builds read the pinned version until a pin is promoted.",
                len(results), n_cov, args.quarter)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
