"""Read-only: what a change to the derivative extractor does, filing by filing, on the cached filings.

    python scripts/v05_evidence/derivative_effect.py <path to the earlier bdc_derivatives.py> [cik ...]

Runs the earlier and the current ``_extract_filing`` on every cached filing of the funds that have
a wrapper (or the funds named) and reports the type-quarters whose net value or notional changes.
Writes nothing. Progress is printed every 100 filings.
"""
import importlib.util
import re
import sys
import time
from pathlib import Path

import pandas as pd
from lxml import etree

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import bdc_derivatives as new  # noqa: E402

spec = importlib.util.spec_from_file_location("bdc_derivatives_before", sys.argv[1])
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
named = {re.sub(r"\D", "", c).zfill(10) for c in sys.argv[2:]}
wrapped = {p.stem for p in (REPO / "data/overrides/bdc_xbrl_wrappers").glob("0*.json")}
index = pd.read_csv(REPO / "data/output/bdc_filings_index.csv", dtype=str)
index["cik10"] = index["cik"].str.replace(r"\D", "", regex=True).str.zfill(10)
index = index[index["cik10"].isin(named or wrapped) & index["xbrl_local_path"].notna() & (index["xbrl_local_path"] != "")]
print("filings to read:", len(index), "| funds:", index["cik10"].nunique(), flush=True)
started, read, with_derivatives, changed = time.time(), 0, 0, []
for _, row in index.iterrows():
    read += 1
    if read % 100 == 0:
        print("  read %d, %d with derivatives, %d changed type-quarters, %.0fs" % (read, with_derivatives, len(changed), time.time() - started), flush=True)
    try:
        blob = Path(row["xbrl_local_path"]).read_bytes()
    except OSError:
        continue
    if b"DerivativeInstrumentRiskAxis" not in blob:
        continue
    try:
        root = etree.fromstring(blob, parser=etree.XMLParser(huge_tree=True))
    except etree.XMLSyntaxError:
        continue
    day = str(row["report_date"])
    before, after = old._extract_filing(root, day), new._extract_filing(root, day)
    types = set(before["per_type_net"]) | set(before["type_notional"]) | set(after["per_type_net"]) | set(after["type_notional"])
    with_derivatives += bool(types)
    for kind in sorted(types):
        b = (before["per_type_net"].get(kind), before["type_notional"].get(kind))
        a = (after["per_type_net"].get(kind), after["type_notional"].get(kind))
        if any(abs((x or 0.0) - (y or 0.0)) > 0.5 for x, y in zip(b, a)):
            changed.append((row["cik10"], str(row.get("entity_name", ""))[:34], day, row["form_type"], kind, b, a))
print("filings read: %d | with derivative facts: %d | type-quarters changed: %d | funds changed: %d" % (
    read, with_derivatives, len(changed), len({c[0] for c in changed})))
million = lambda v: "-" if v is None else "%.1f" % (v / 1e6)
for cik, name, day, form, kind, b, a in changed[:70]:
    print("   %s %-34s %s %-5s %-22s net %s -> %s | notional %s -> %s" % (cik, name, day, form, kind, million(b[0]), million(a[0]), million(b[1]), million(a[1])))
