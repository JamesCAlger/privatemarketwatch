"""Read-only: what the page-labelled context reading would adopt for one fund, filing by filing.

    python scripts/v05_evidence/page_labelled_dry_run.py <cik> [accession no dashes]

Parses each cached XBRL instance of the fund, applies the wrapper's page_labelled_contexts, and
prints per filing and period: contexts adopted and their fair value, with the first few identifiers.
"""
import sys
from collections import defaultdict
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import bdc_filings as f  # noqa: E402
from pipeline.config import BDC_XBRL_CACHE_DIR  # noqa: E402
from pipeline.page_labelled_contexts import adopt_page_labelled_contexts  # noqa: E402

cik = sys.argv[1].zfill(10)
only = sys.argv[2] if len(sys.argv) > 2 else None
for xml in sorted((BDC_XBRL_CACHE_DIR / cik.lstrip("0")).glob("*.xml")):
    if only and xml.stem != only:
        continue
    tree = etree.parse(str(xml), etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True, load_dtd=False))
    contexts = f._parse_xbrl_contexts(tree)
    before = {c for c, info in contexts.items() if info["is_investment"]}
    n = adopt_page_labelled_contexts(contexts, {"cik": cik, "accession_number": xml.stem})
    adopted = {c for c, info in contexts.items() if info["is_investment"]} - before
    rows = [r for r in f._extract_investment_facts(tree, contexts) if r["_context_id"] in adopted]
    by_period = defaultdict(lambda: [0, 0.0])
    for r in rows:
        by_period[r["period"]][0] += 1
        by_period[r["period"]][1] += r.get("fair_value") or 0.0
    print("%s | adopted %d | %s" % (xml.stem, n, " ; ".join("%s: %d rows, %.1fM" % (p, v[0], v[1] / 1e6) for p, v in sorted(by_period.items()))), flush=True)
    for r in (rows if only else []):
        print(("      %s | fv %s | cost %s | principal %s | rate %s | maturity %s" % (
            r["investment_identifier"], r.get("fair_value"), r.get("cost"), r.get("principal_amount"), r.get("interest_rate"), r.get("maturity_date"))).encode("ascii", "replace").decode())
