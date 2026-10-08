"""Read-only: per schedule block, the tagged position rows against the block's printed subtotal.

    python scripts/v05_evidence/page_block_sums.py <cik> <accession no dashes> <quarter> [tolerance $K, default 2]

Walks the page's rows in order. Rows whose fair-value tag sits on an identifier context of the
quarter accumulate; a row whose tag sits on any other context of the quarter and prints amounts
only closes the block. A block whose rows do not sum to its subtotal is printed with its rows.
A group of one row has no subtotal row, so a block passes when its last k rows add to the subtotal.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import page_labelled_contexts as plc  # noqa: E402

cik, accession, quarter = sys.argv[1].lstrip("0"), sys.argv[2], sys.argv[3]
tolerance = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
raw = (REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
contexts = {}
for match in re.finditer(r"<xbrli:context[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</xbrli:context>", raw, flags=re.S):
    body = match.group(2)
    instant = re.search(r"<xbrli:instant>([^<]*)<", body)
    if instant and instant.group(1) == quarter:
        contexts[match.group(1)] = "InvestmentIdentifierAxis" in body
block, shown = [], 0
for chunk in re.split(r"<tr\b", raw, flags=re.I)[1:]:
    if "InvestmentOwnedAtFairValue" not in chunk:
        continue
    row = re.split(r"</tr>", chunk, maxsplit=1, flags=re.I)[0]
    tag = re.search(r'<ix:nonFraction\b([^>]*name="[^"]*:InvestmentOwnedAtFairValue"[^>]*)>([^<]*)<', row)
    if not tag:
        continue
    ctx = re.search(r'contextRef="([^"]*)"', tag.group(1)).group(1)
    if ctx not in contexts:
        continue
    scale = re.search(r'scale="(-?\d+)"', tag.group(1))
    digits = "0" if "&#8212" in tag.group(2) else re.sub(r"[^0-9.]", "", tag.group(2))
    value = (-1.0 if 'sign="-"' in tag.group(1) else 1.0) * float(digits or 0) * 10 ** int(scale.group(1) if scale else 0) / 1e3
    cells = plc._cell_texts(row)
    if contexts[ctx]:
        block.append((value, " | ".join(cells)[:150]))
        continue
    label = cells[0] if cells else ""
    if re.search(r"[A-Za-z]{2}", label) and not label.lower().startswith("total"):
        continue
    if label.lower().startswith("total"):
        block = []
        continue
    total = sum(v for v, _ in block)
    running, suffix_ok = 0.0, False
    for v, _ in reversed(block):
        running += v
        if abs(running - value) <= tolerance:
            suffix_ok = True
            break
    if block and not suffix_ok:
        shown += 1
        print(("block subtotal %.0f | rows sum %.0f | difference %.0f | rows %d" % (value, total, total - value, len(block))))
        for v, text in block[-12:]:
            print(("      %10.0f | %s" % (v, text)).encode("ascii", "replace").decode())
    block = []
print("blocks that do not add:", shown)
