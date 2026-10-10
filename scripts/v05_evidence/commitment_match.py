"""Read-only: match a filer's tagged unfunded commitments to its schedule rows, per cached filing.

    python scripts/v05_evidence/commitment_match.py <cik> [accession with dashes]

For each filing: commitments tagged, commitments matched to a schedule row of the same date
whose principal and cost equal the commitment, the matched sum, and the unmatched ones.
"""
import re
import sys
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline.bdc_filings import _extract_investment_facts, _local_name, parse_filing_contexts  # noqa: E402
from pipeline.unfunded_commitments import COMMITMENT_CONCEPT, match_commitments  # noqa: E402

cik = sys.argv[1].lstrip("0")
only = sys.argv[2].replace("-", "") if len(sys.argv) > 2 else ""
folder = REPO / "data/raw/filings/bdc_xbrl" / cik
parser = etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True, load_dtd=False)
print("accession | period | commitments | matched | matched $K | unmatched $K | first unmatched")
for path in sorted(folder.glob("*.xml")):
    if only and path.stem != only:
        continue
    accession = "%s-%s-%s" % (path.stem[:10], path.stem[10:12], path.stem[12:])
    tree = etree.parse(str(path), parser)
    meta = {"cik": cik.zfill(10), "accession_number": accession}
    contexts = parse_filing_contexts(tree, meta)
    facts = _extract_investment_facts(tree, contexts)
    commitments = []
    for elem in tree.getroot().iter():
        if not isinstance(elem.tag, str) or _local_name(elem.tag).lower() != COMMITMENT_CONCEPT:
            continue
        info = contexts.get(elem.get("contextRef") or "")
        text = (elem.text or "").strip()
        if info and info.get("investment_identifier") and re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            commitments.append((info["period"], info["investment_identifier"], float(text)))
    by_period = {}
    for period, identifier, amount in commitments:
        by_period.setdefault(period, []).append((identifier, amount))
    for period in sorted(by_period):
        rows = [r for r in facts if r["period"] == period]
        matched, unmatched = match_commitments(by_period[period], rows)
        print("%s | %s | %d | %d | %.0f | %.0f | %s" % (
            accession, period, len(by_period[period]), len(matched),
            sum(a for _, a in matched) / 1e3, sum(a for _, a in unmatched) / 1e3,
            "; ".join("%s %.0f" % (i[:40], a / 1e3) for i, a in unmatched[:3])))
