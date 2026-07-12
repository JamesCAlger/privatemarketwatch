"""Fetch the FRED SOFR 90-day average (a free ~3M Term-SOFR proxy) and cache to disk.

ONE network call to FRED's no-API-key CSV endpoint; the series is then read from cache by
pipeline.sofr_reference. Re-run only to refresh. CME Term SOFR (the exact 1M/3M index) is
not free on FRED -- SOFR90DAYAVG (backward-looking compounded avg) is the public proxy.

Usage: python scripts/fetch_sofr.py
"""
import csv
import io
import urllib.request

from pipeline import config

SERIES = "SOFR90DAYAVG"
URL = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES}"
OUT = config.DATA_DIR / "reference" / "sofr_90day_avg.csv"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {SERIES} from FRED ...")
    req = urllib.request.Request(URL, headers={"User-Agent": "evergreen-funds-research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    reader = csv.reader(io.StringIO(raw))
    header = next(reader)
    # FRED CSV: first col is the date, second the value; value '.' means missing
    rows = []
    for r in reader:
        if len(r) < 2:
            continue
        date, val = r[0].strip(), r[1].strip()
        if val in ("", "."):
            continue
        rows.append((date, val))

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "sofr_90day_avg_pct"])
        w.writerows(rows)
    print(f"Cached {len(rows)} observations ({rows[0][0]} .. {rows[-1][0]}) -> {OUT}")


if __name__ == "__main__":
    main()
