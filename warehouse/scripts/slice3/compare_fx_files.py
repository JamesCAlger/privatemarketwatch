"""Slice 3 Task 3 fix round 1: compare the FRED H.10 CSV the warehouse reads with the admitted quotes.json production's
principal_reference_table reads (pipeline/monetary_fx.py). Read-only. Prints currencies, date ranges, row counts and
every (date, currency) present in one file only or with a different rate text (first 20 of each).

Usage (from the repository root):
  warehouse\\.venv\\Scripts\\python.exe warehouse\\scripts\\slice3\\compare_fx_files.py
"""
import csv
import json
import os
import sys
import threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FOLDER = os.path.join(ROOT, "data", "reference", "monetary_conversion")
LIMIT = 20

timer = threading.Timer(120, lambda: os._exit(2))
timer.start()
try:
    csv_rates = {}
    with open(os.path.join(FOLDER, "fred_h10_usd_per_unit.csv"), encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            csv_rates[(row["date"], row["currency"])] = row["usd_per_unit"]
    with open(os.path.join(FOLDER, "quotes.json"), encoding="utf-8-sig") as fh:
        package = json.load(fh)
    quote_rates = {}
    providers = set()
    sources = set()
    for quote in package["quotes"]:
        providers.add(quote.get("provider"))
        sources.add((quote["source"]["path"], quote["source"]["sha256"]))
        for currency, rate in quote["usd_per_unit"].items():
            quote_rates[(quote["date"], currency)] = str(rate)

    def describe(name, rates):
        dates = sorted({d for d, _ in rates})
        currencies = sorted({c for _, c in rates})
        print(f"{name}: rows {len(rates)}, dates {len(dates)} ({dates[0]} to {dates[-1]}), currencies {len(currencies)}: "
              + ",".join(currencies))

    describe("csv", csv_rates)
    describe("quotes.json", quote_rates)
    print("quotes.json providers:", sorted(p for p in providers if p), "source files:", sorted(sources))
    only_csv = sorted(set(csv_rates) - set(quote_rates))
    only_quotes = sorted(set(quote_rates) - set(csv_rates))
    differ = sorted(k for k in set(csv_rates) & set(quote_rates) if csv_rates[k] != quote_rates[k])
    print("only in csv:", len(only_csv), only_csv[:LIMIT])
    print("only in quotes.json:", len(only_quotes), only_quotes[:LIMIT])
    print("rate text differs:", len(differ), [(k, csv_rates[k], quote_rates[k]) for k in differ[:LIMIT]])
finally:
    timer.cancel()
sys.exit(0)
