"""Read-only: printed schedule lines for a phrase in a cached filing, skipping the hidden context-header blocks.

    python scripts/v05_evidence/page_line.py <cik> <accession with dashes> "<phrase>" [max hits] [chars after] [chars before]

The text is normalised exactly as the fund gate compares quotes (scripts/v05_evidence/fund_gate.py),
so a line copied from this output verifies as printed.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fund_gate import normalise, page_text  # noqa: E402

cik, accession, phrase = sys.argv[1].zfill(10), sys.argv[2], normalise(sys.argv[3])
if "-" not in accession:
    accession = "%s-%s-%s" % (accession[:10], accession[10:12], accession[12:])
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 4
after = int(sys.argv[5]) if len(sys.argv) > 5 else 350
before = int(sys.argv[6]) if len(sys.argv) > 6 else 60
text = page_text(cik, accession)
if text is None:
    raise SystemExit("filing not in the cache: %s %s" % (cik, accession))
shown = 0
for match in re.finditer(re.escape(phrase), text, flags=re.I):
    window = text[match.start(): match.start() + 200]
    if re.search(r"\d{4}-\d{2}-\d{2} 0\d{9}", window) or "Member" in window[:160]:
        continue
    shown += 1
    if shown > limit:
        break
    print("   [%d] ...%s" % (match.start(), text[max(0, match.start() - before): match.start() + after]))
print("hits shown:", min(shown, limit))
