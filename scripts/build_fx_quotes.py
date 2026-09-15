"""Build the admitted FX quote package from the cached FRED H.10 series.

Reads data/reference/fx_fred/<SERIES>.csv (written by scripts/fetch_fx_fred.py),
writes data/reference/monetary_conversion/:
  fred_h10_usd_per_unit.csv   one retained source file (date,currency,series,usd_per_unit)
  quotes.json                 one quote per observation date: {date, provider, quote_id,
                              usd_per_unit:{CCY:rate}, series:{CCY:id}, source:{path,sha256}}
  admission_manifest.json     promoted entry for quotes.json via rule_admission

No network. Re-run after refreshing the FRED cache; the release fingerprint
changes because the quote source hash changes.

Usage: python -m scripts.build_fx_quotes [--since 2018-10-01]
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline import config
from pipeline.programme.core import atomic_json, sha
from pipeline.rule_admission import register_promotion

SOURCE_DIR = config.DATA_DIR / "reference" / "fx_fred"
PACKAGE_DIR = config.REFERENCE_DIR / "monetary_conversion"
SOURCE_NAME = "fred_h10_usd_per_unit.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2018-10-01")
    args = parser.parse_args()
    fetch_manifest = json.loads((SOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    rows: list[tuple[str, str, str, str]] = []
    for currency, meta in sorted(fetch_manifest["series"].items()):
        path = SOURCE_DIR / f"{meta['series']}.csv"
        if sha(path) != meta["normalized_sha256"]:
            raise ValueError("Cached FRED series changed since fetch: " + str(path))
        with path.open(newline="", encoding="utf-8") as stream:
            for r in csv.DictReader(stream):
                if r["date"] >= args.since:
                    rows.append((r["date"], r["currency"], r["series"], r["usd_per_unit"]))
    rows.sort()
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    source = PACKAGE_DIR / SOURCE_NAME
    with source.open("w", newline="", encoding="utf-8") as stream:
        w = csv.writer(stream)
        w.writerow(["date", "currency", "series", "usd_per_unit"])
        w.writerows(rows)
    source_hash = sha(source)
    by_date: dict[str, dict] = {}
    for date, currency, series, rate in rows:
        q = by_date.setdefault(date, dict(date=date, provider="FRED", quote_id="FRED-H10-" + date,
                                          usd_per_unit={}, series={},
                                          source=dict(path=SOURCE_NAME, sha256=source_hash)))
        q["usd_per_unit"][currency] = rate
        q["series"][currency] = series
    quotes = [by_date[d] for d in sorted(by_date)]
    quotes_path = PACKAGE_DIR / "quotes.json"
    quotes_path.write_text(json.dumps(dict(format_version=1, provider="FRED", release="H.10",
        fetched_utc=fetch_manifest["fetched_utc"], since=args.since, quotes=quotes), indent=0),
        encoding="utf-8")
    evidence = dict(kind="fx_reference_package", provider="FRED", release="H.10",
        fetched_utc=fetch_manifest["fetched_utc"], fetch_manifest_sha256=sha(SOURCE_DIR / "manifest.json"),
        source_sha256=source_hash, quote_dates=len(quotes), currencies=sorted(fetch_manifest["series"]),
        authorization="owner decision 2026-09-15: single canonical FX source (FRED H.10), replaces ECB contract",
        built_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        gate=dict(verdict="PASS", checks=["cached_series_hash_matches_fetch_manifest",
                                           "positive_finite_rates", "one_quote_per_date"]))
    manifest = PACKAGE_DIR / "admission_manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        data["entries"]["quotes.json"] = dict(admission_status="promoted", sha256=sha(quotes_path), evidence=evidence)
        atomic_json(manifest, data)
    else:
        register_promotion(PACKAGE_DIR, quotes_path, evidence=evidence)
    print(f"{len(rows)} observations, {len(quotes)} quote dates since {args.since}; "
          f"source sha {source_hash[:12]} -> {PACKAGE_DIR}", flush=True)


if __name__ == "__main__":
    main()
