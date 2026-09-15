"""Fetch Federal Reserve H.10 daily FX series from FRED and cache them to disk.

One network call per series to FRED's no-API-key CSV endpoint (same endpoint as
scripts/fetch_sofr.py). The cached files are the only FX source the pipeline
reads; re-run only to refresh. FRED is NOT SEC EDGAR, so the SEC rate limit does
not apply, but the calls are still serial and few.

Conventions (from the H.10 release):
  DEXUS?? series quote USD per one unit of the foreign currency (EUR, GBP, AUD, NZD).
  DEX??US series quote foreign units per one USD (CAD, CHF, JPY, NOK, SEK, ...).
Both are normalised here to ``usd_per_unit``.

Usage: python scripts/fetch_fx_fred.py [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from pipeline import config

# currency -> (FRED series id, quote direction)
SERIES: dict[str, tuple[str, str]] = {
    "EUR": ("DEXUSEU", "usd_per_unit"),
    "GBP": ("DEXUSUK", "usd_per_unit"),
    "AUD": ("DEXUSAL", "usd_per_unit"),
    "NZD": ("DEXUSNZ", "usd_per_unit"),
    "CAD": ("DEXCAUS", "units_per_usd"),
    "CHF": ("DEXSZUS", "units_per_usd"),
    "JPY": ("DEXJPUS", "units_per_usd"),
    "NOK": ("DEXNOUS", "units_per_usd"),
    "SEK": ("DEXSDUS", "units_per_usd"),
    "DKK": ("DEXDNUS", "units_per_usd"),
    "MXN": ("DEXMXUS", "units_per_usd"),
    "SGD": ("DEXSIUS", "units_per_usd"),
    "HKD": ("DEXHKUS", "units_per_usd"),
    "INR": ("DEXINUS", "units_per_usd"),
    "BRL": ("DEXBZUS", "units_per_usd"),
    "ZAR": ("DEXSFUS", "units_per_usd"),
    "KRW": ("DEXKOUS", "units_per_usd"),
    "CNY": ("DEXCHUS", "units_per_usd"),
    "TWD": ("DEXTAUS", "units_per_usd"),
    "THB": ("DEXTHUS", "units_per_usd"),
    "MYR": ("DEXMAUS", "units_per_usd"),
    "LKR": ("DEXSLUS", "units_per_usd"),
}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
DEFAULT_OUT = config.DATA_DIR / "reference" / "fx_fred"


def fetch_series(series: str) -> tuple[str, list[tuple[str, str]]]:
    req = urllib.request.Request(URL.format(series=series),
                                 headers={"User-Agent": "evergreen-funds-research/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    reader = csv.reader(io.StringIO(raw))
    next(reader)
    rows = []
    for r in reader:
        if len(r) < 2:
            continue
        date, val = r[0].strip(), r[1].strip()
        if val in ("", "."):
            continue
        rows.append((date, val))
    return raw, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"provider": "FRED", "release": "H.10", "fetched_utc":
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "series": {}}
    for currency, (series, direction) in SERIES.items():
        print(f"Fetching {series} ({currency}, {direction}) ...", flush=True)
        raw, rows = fetch_series(series)
        raw_path = out / f"{series}.raw.csv"
        raw_path.write_text(raw, encoding="utf-8")
        norm_path = out / f"{series}.csv"
        with norm_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "currency", "series", "usd_per_unit"])
            for date, val in rows:
                rate = Decimal(val)
                usd = rate if direction == "usd_per_unit" else (Decimal(1) / rate)
                w.writerow([date, currency, series, str(usd)])
        manifest["series"][currency] = {
            "series": series, "direction": direction, "observations": len(rows),
            "first": rows[0][0] if rows else None, "last": rows[-1][0] if rows else None,
            "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "normalized_sha256": hashlib.sha256(norm_path.read_bytes()).hexdigest(),
            "url": URL.format(series=series),
        }
        print(f"  {len(rows)} observations {rows[0][0] if rows else '-'} .. {rows[-1][0] if rows else '-'}",
              flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote manifest -> {out / 'manifest.json'}")


if __name__ == "__main__":
    main()
