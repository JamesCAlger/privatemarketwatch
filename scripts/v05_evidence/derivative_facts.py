"""Read-only: the derivative facts of one cached filing, with every dimension of their context.

    python scripts/v05_evidence/derivative_facts.py <sandbox label> <cik> <report date>

Lists each net-value or notional fact dated at the report date whose context is on the
derivative-risk axis: concept, value, and the context's dimensions. Use it to see which facts
are a total and which are a breakdown of that total.
"""
import re
import sys
from pathlib import Path

import pandas as pd
from lxml import etree

REPO = Path(__file__).resolve().parents[2]
label, cik, day = sys.argv[1], re.sub(r"\D", "", sys.argv[2]).zfill(10), sys.argv[3]
index = pd.read_csv(REPO / "scratch/fund_sandbox" / label / "output" / "bdc_filings_index.csv", dtype=str)
index = index[(index["cik"].str.zfill(10) == cik) & (index["report_date"] == day)]
for _, row in index.iterrows():
    root = etree.fromstring(Path(row["xbrl_local_path"]).read_bytes(), parser=etree.XMLParser(huge_tree=True))
    contexts = {}
    for ctx in root.iter():
        if not isinstance(ctx.tag, str) or not ctx.tag.endswith("}context"):
            continue
        end, dims = "", []
        for el in ctx.iter():
            name = el.tag.split("}")[-1] if isinstance(el.tag, str) else ""
            if name in ("instant", "endDate"):
                end = (el.text or "").strip()
            elif name in ("explicitMember", "typedMember"):
                member = (el.text or "").strip() or "".join(el.itertext()).strip()
                dims.append("%s=%s" % (el.get("dimension", "").split(":")[-1], member.split(":")[-1][:40]))
        contexts[ctx.get("id")] = (end, dims)
    print(row["accession_number"], row["form_type"])
    shown = 0
    for el in root.iter():
        ref = el.get("contextRef")
        if not ref or ref not in contexts or not isinstance(el.tag, str):
            continue
        end, dims = contexts[ref]
        local = el.tag.split("}")[-1]
        if end != day or not re.search(r"Derivative|Notional", local) or not any("DerivativeInstrumentRiskAxis" in d for d in dims):
            continue
        print("   %-58s %16s | %s" % (local[:58], (el.text or "").strip()[:16], " ; ".join(dims)))
        shown += 1
        if shown >= 60:
            break
