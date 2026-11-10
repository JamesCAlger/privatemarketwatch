"""Download the SEC companyfacts JSON for named funds into the snapshot store.

NETWORK: calls SEC EDGAR (one request per fund). Run only when the owner has asked for it.

    python scripts/download_companyfacts.py --ciks 0001803498 0001812554 --expect 2026-06-30 \
        [--candidate-pin scratch/<session>/companyfacts_pin.json]

Each download is stored as a new immutable snapshot under ``data/raw/companyfacts_snapshots/``
(source api_download; identical bytes are not stored twice). The published pin
(``data/reference/companyfacts_pins/published.json``) is NEVER moved: builds keep reading the
pinned version. ``--candidate-pin`` writes a pin file (published pin + these funds' new snapshots)
for a sandbox build via ``PM_COMPANYFACTS_PIN``; promoting it is a separate, deliberate step
(``scripts/companyfacts_snapshots.py pin --published --yes``).

Reports, per fund, how many facts end on the expected date and how the download compares with
the currently pinned version (fact counts, latest end date, restated facts).
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
    parser.add_argument("--candidate-pin", type=Path, default=None,
                        help="write a candidate pin file (never the published pin)")
    args = parser.parse_args(argv)

    from pipeline import companyfacts_store as store
    from pipeline.edgar_client import EdgarClient

    client = EdgarClient()
    missing = 0
    repins: dict[str, str] = {}
    for cik in sorted({store.cik10(c) for c in args.ciks}):
        data = client.get_json("https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json" % cik)
        row, created = store.add_snapshot(cik, json.dumps(data).encode("utf-8"), source="api_download")
        repins[cik] = row["path"]
        new = _ends(data)
        old_data = store.load_companyfacts(cik)
        old = _ends(old_data)
        restated = store.diff_facts(old_data, data, limit=0)["summary"] if old_data else None
        missing += 0 if new.get(args.expect) else 1
        print("%s %s | facts ending %s: %d | facts in all: %d (pinned: %d, latest end there %s) | "
              "vs pinned: %s | snapshot %s (%s)" % (
                  cik, data.get("entityName", ""), args.expect, new.get(args.expect, 0), sum(new.values()),
                  sum(old.values()), max((d for d in old if d <= "2030"), default=""),
                  ("restated %(restated)d added %(added)d removed %(removed)d" % restated) if restated else "no pinned version",
                  row["path"], "new" if created else "already stored"))
    if args.candidate_pin is not None and repins:
        store.write_candidate_pin(args.candidate_pin, repins, promoted_by="scripts/download_companyfacts.py",
                                  note="candidate: downloads for " + args.expect)
        print("candidate pin written: %s (published pin unchanged)" % args.candidate_pin)
    print("funds without facts for %s: %d" % (args.expect, missing))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
