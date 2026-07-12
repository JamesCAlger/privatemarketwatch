"""Refresh universe entity names from the SEC submissions API.

Universe entity names come from EFTS ``display_names`` captured at discovery
time, which are frozen at the filing-date name. Funds that rename after their
election filing (e.g. Owl Rock -> Blue Owl, mid-2023) keep the stale name in
``combined_universe.csv`` and everything downstream (fund_financials backfill,
frontend fund list and detail pages).

This script:
  1. Fetches https://data.sec.gov/submissions/CIK{cik10}.json for each
     universe CIK via the rate-limited EdgarClient (one request per CIK).
  2. Writes an audited overlay ``data/reference/entity_current_names.csv``
     (cik, entity_name, previous_name, changed, fetched_date, source).
  3. Applies the overlay to combined_universe.csv / .json in place.

``pipeline.merge`` re-applies the overlay on future universe rebuilds, so the
refresh survives rediscovery. After running this, rebuild fund financials and
re-export frontend JSON:

    python scripts/rebuild_outputs.py --financials
    python -m pipeline.main --export-frontend

NETWORK: this is an explicit-download script (one submissions request per
universe CIK, ~600 requests for the full universe). Run only when the user
asks for a name refresh.

Usage:
    python scripts/refresh_entity_names.py                    # all universe CIKs
    python scripts/refresh_entity_names.py --ciks 1812554 1869453
    python scripts/refresh_entity_names.py --dry-run          # fetch + report only
"""

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline.config import (
    COMBINED_UNIVERSE_FILE,
    COMBINED_UNIVERSE_JSON,
    ENTITY_CURRENT_NAMES_FILE,
)
from pipeline.edgar_client import EdgarClient
from pipeline.merge import _apply_entity_name_overlay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("refresh_entity_names")

_CIK_SUFFIX_RE = re.compile(r"\s*\(CIK\s+\d+\)\s*")


def _clean_name(name: str) -> str:
    """Strip EFTS '(CIK NNNN)' annotations and collapse whitespace."""
    return " ".join(_CIK_SUFFIX_RE.sub(" ", name or "").split()).strip()


def fetch_current_names(ciks: list[str]) -> pd.DataFrame:
    """Fetch current registrant names for CIKs from the submissions API."""
    client = EdgarClient()
    rows: list[dict] = []
    failures = 0
    for i, cik in enumerate(ciks, 1):
        try:
            data = client.get_company_submissions(cik)
            name = str(data.get("name", "") or "").strip()
        except Exception as exc:
            logger.warning("CIK %s: submissions fetch failed: %s", cik, exc)
            failures += 1
            continue
        if not name:
            logger.warning("CIK %s: submissions JSON has no name", cik)
            failures += 1
            continue
        rows.append({"cik": cik.zfill(10), "entity_name": name})
        if i % 50 == 0:
            logger.info("Fetched %d/%d submissions ...", i, len(ciks))
    logger.info("Fetched %d names, %d failures", len(rows), failures)
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh universe entity names from SEC submissions API")
    parser.add_argument("--ciks", nargs="+", default=None,
                        help="Limit to these CIKs (default: all universe CIKs)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and report renames without writing files")
    args = parser.parse_args()

    if not COMBINED_UNIVERSE_FILE.exists():
        logger.error("Universe file not found: %s", COMBINED_UNIVERSE_FILE)
        return 1

    universe = pd.read_csv(COMBINED_UNIVERSE_FILE, dtype=str)
    universe["cik"] = universe["cik"].astype(str).str.strip().str.zfill(10)

    if args.ciks:
        wanted = {c.strip().zfill(10) for c in args.ciks}
        ciks = sorted(wanted & set(universe["cik"]))
        missing = wanted - set(ciks)
        if missing:
            logger.warning("CIKs not in universe (skipped): %s",
                           ", ".join(sorted(missing)))
    else:
        ciks = sorted(universe["cik"].dropna().unique())

    logger.info("Refreshing entity names for %d CIKs", len(ciks))
    fetched = fetch_current_names(ciks)
    if fetched.empty:
        logger.error("No names fetched -- aborting without changes")
        return 1

    # Compare against current universe names (ignoring the EFTS CIK suffix)
    old_by_cik = (universe.dropna(subset=["entity_name"])
                  .drop_duplicates("cik")
                  .set_index("cik")["entity_name"].to_dict())
    fetched["previous_name"] = fetched["cik"].map(old_by_cik).fillna("")
    fetched["changed"] = [
        _clean_name(p).lower() != n.strip().lower()
        for p, n in zip(fetched["previous_name"], fetched["entity_name"])
    ]
    fetched["fetched_date"] = datetime.now(timezone.utc).date().isoformat()
    fetched["source"] = "sec_submissions"

    renames = fetched[fetched["changed"]]
    logger.info("Renames detected: %d of %d CIKs", len(renames), len(fetched))
    for _, r in renames.iterrows():
        logger.info("  %s: '%s' -> '%s'",
                    r["cik"], _clean_name(r["previous_name"]), r["entity_name"])

    if args.dry_run:
        logger.info("Dry run -- no files written")
        return 0

    # Merge into any existing overlay so partial (--ciks) runs do not drop
    # previously refreshed names.
    if ENTITY_CURRENT_NAMES_FILE.exists():
        existing = pd.read_csv(ENTITY_CURRENT_NAMES_FILE, dtype=str)
        existing["cik"] = existing["cik"].astype(str).str.strip().str.zfill(10)
        existing = existing[~existing["cik"].isin(set(fetched["cik"]))]
        overlay = pd.concat([existing, fetched], ignore_index=True)
    else:
        overlay = fetched
    overlay = overlay.sort_values("cik")
    cols = ["cik", "entity_name", "previous_name", "changed",
            "fetched_date", "source"]
    overlay.to_csv(ENTITY_CURRENT_NAMES_FILE, index=False,
                   columns=[c for c in cols if c in overlay.columns])
    logger.info("Wrote overlay: %s (%d CIKs)",
                ENTITY_CURRENT_NAMES_FILE, len(overlay))

    # Apply to the universe artifacts in place
    updated = _apply_entity_name_overlay(universe,
                                         overlay_file=ENTITY_CURRENT_NAMES_FILE)
    updated.to_csv(COMBINED_UNIVERSE_FILE, index=False)
    updated.to_json(COMBINED_UNIVERSE_JSON, orient="records", indent=2,
                    date_format="iso")
    logger.info("Updated %s and %s", COMBINED_UNIVERSE_FILE.name,
                COMBINED_UNIVERSE_JSON.name)
    logger.info("Next: python scripts/rebuild_outputs.py --financials "
                "&& python -m pipeline.main --export-frontend")
    return 0


if __name__ == "__main__":
    sys.exit(main())
