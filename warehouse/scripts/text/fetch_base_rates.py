"""Fetch public base-rate series from FRED and write them as two warehouse seeds (owner's go, 2026-11-26).

One serial request per series to FRED's no-key CSV endpoint (the endpoint scripts/fetch_sofr.py and
scripts/fetch_fx_fred.py use). FRED is not SEC EDGAR. Standard library only. ASCII output.

Usage: python fetch_base_rates.py <seeds_dir> <manifest_json> [--from YYYY-MM-DD]
Writes <seeds_dir>/base_rate_fred.csv (series_id,date,value_pct) and <seeds_dir>/base_rate_series.csv
(series_id,rate_name,frequency,kind,note), and the manifest (per series: url, rows, first and last date, sha256 of the
bytes received, time fetched). A series that fails or is empty is reported and left out; the run does not stop.

What these are, and are not: SOFR, SONIA, the prime rate and the fed funds rate are the published daily rates.
The "3-month interbank" series are OECD monthly averages per currency: a proxy for EURIBOR, CDOR/CORRA, BBSW/BBSY,
STIBOR, SARON, NIBOR, TONA, KORIBOR and BKBM, not those benchmarks themselves. Term SOFR and LIBOR are licensed
and are not here. The check that reads these uses a window and a tolerance for that reason.
"""
import csv
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
# series id -> (rate name used by the rules, frequency, kind, note)
SERIES = {
    "SOFR": ("SOFR", "daily", "published", "Secured Overnight Financing Rate"),
    "SOFR30DAYAVG": ("SOFR", "daily", "average", "30-day average SOFR"),
    "SOFR90DAYAVG": ("SOFR", "daily", "average", "90-day average SOFR"),
    "SOFR180DAYAVG": ("SOFR", "daily", "average", "180-day average SOFR"),
    "IUDSOIA": ("SONIA", "daily", "published", "Sterling Overnight Index Average"),
    "DPRIME": ("PRIME", "daily", "published", "Bank prime loan rate"),
    "DFF": ("FEDFUNDS", "daily", "published", "Effective federal funds rate"),
    "IR3TIB01USM156N": ("LIBOR", "monthly", "proxy", "OECD 3-month interbank rate, United States: proxy for USD LIBOR"),
    "IR3TIB01EZM156N": ("EURIBOR", "monthly", "proxy", "OECD 3-month interbank rate, euro area: proxy for EURIBOR"),
    "IR3TIB01GBM156N": ("SONIA", "monthly", "proxy", "OECD 3-month interbank rate, United Kingdom"),
    "IR3TIB01CAM156N": ("CORRA", "monthly", "proxy", "OECD 3-month interbank rate, Canada: proxy for CDOR and CORRA"),
    "IR3TIB01AUM156N": ("BBSW", "monthly", "proxy", "OECD 3-month interbank rate, Australia: proxy for BBSW and BBSY"),
    "IR3TIB01NZM156N": ("BKBM", "monthly", "proxy", "OECD 3-month interbank rate, New Zealand: proxy for BKBM"),
    "IR3TIB01SEM156N": ("STIBOR", "monthly", "proxy", "OECD 3-month interbank rate, Sweden: proxy for STIBOR"),
    "IR3TIB01CHM156N": ("SARON", "monthly", "proxy", "OECD 3-month interbank rate, Switzerland: proxy for SARON"),
    "IR3TIB01NOM156N": ("NIBOR", "monthly", "proxy", "OECD 3-month interbank rate, Norway: proxy for NIBOR"),
    "IR3TIB01JPM156N": ("TONA", "monthly", "proxy", "OECD 3-month interbank rate, Japan: proxy for TONA/TONAR"),
    "IR3TIB01KRM156N": ("KORIBOR", "monthly", "proxy", "OECD 3-month interbank rate, Korea: proxy for KORIBOR"),
}

seeds, manifest_path = Path(sys.argv[1]), Path(sys.argv[2])
start = sys.argv[sys.argv.index("--from") + 1] if "--from" in sys.argv else "2021-06-01"
rows, manifest, meta = [], {}, []
for sid, (name, freq, kind, note) in SERIES.items():
    url = URL.format(series=sid)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "base-rate-fetch/1.0"})
        with urllib.request.urlopen(req, timeout=40) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"{sid}: FAILED {type(e).__name__} {e}")
        manifest[sid] = {"url": url, "error": str(e)}
        continue
    got = []
    for r in csv.reader(io.StringIO(raw.decode("utf-8"))):
        if len(r) < 2 or not r[0][:4].isdigit():
            continue
        try:
            v = float(r[1])
        except ValueError:
            continue  # FRED writes "." for a day with no value
        if r[0] >= start:
            got.append((sid, r[0], repr(round(v, 6))))
    if not got:
        print(f"{sid}: no rows since {start}")
        manifest[sid] = {"url": url, "error": "no rows"}
        continue
    rows.extend(got)
    meta.append((sid, name, freq, kind, note))
    manifest[sid] = {"url": url, "rows": len(got), "first": got[0][1], "last": got[-1][1],
                     "sha256_received": hashlib.sha256(raw).hexdigest(),
                     "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    print(f"{sid}: {len(got)} rows {got[0][1]} to {got[-1][1]} last value {got[-1][2]}")
with open(seeds / "base_rate_fred.csv", "w", newline="\n", encoding="utf-8") as fh:
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(["series_id", "date", "value_pct"])
    w.writerows(rows)
with open(seeds / "base_rate_series.csv", "w", newline="\n", encoding="utf-8") as fh:
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(["series_id", "rate_name", "frequency", "kind", "note"])
    w.writerows(meta)
manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
print("series written", len(meta), "of", len(SERIES), "rows", len(rows))
