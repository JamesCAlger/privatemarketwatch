"""Read-only: the cached company facts of one fund for concepts matching a pattern, around a date.

    python scripts/v05_evidence/companyfacts_concept.py <cik> <regex on concept name> [YYYY-MM prefix of end date]

Prints concept, unit, end date, value, form, fiscal period and frame, at most 60 rows. Use it to see
which filed fact a fund-level figure came from, and what else the filer filed for that date.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, pattern = sys.argv[1].zfill(10), re.compile(sys.argv[2], re.I)
prefix = sys.argv[3] if len(sys.argv) > 3 else ""
data = json.loads((REPO / "data/raw/companyfacts_cache" / (cik + ".json")).read_text(encoding="utf-8"))
shown = 0
for taxonomy, concepts in data.get("facts", {}).items():
    for name, body in sorted(concepts.items()):
        if not pattern.search(name):
            continue
        for unit, facts in body.get("units", {}).items():
            for fact in facts:
                if not str(fact.get("end", "")).startswith(prefix):
                    continue
                shown += 1
                if shown <= 60:
                    print("   %s:%s | %s | %s to %s | %s | %s %s | %s" % (
                        taxonomy, name, unit, fact.get("start", ""), fact.get("end"), fact.get("val"), fact.get("form"),
                        fact.get("fp", ""), fact.get("frame", "")))
print("facts shown:", min(shown, 60), "of", shown)
