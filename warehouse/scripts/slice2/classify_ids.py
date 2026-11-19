"""Diagnostic only: print production's wrapper classification (pipeline.bdc_xbrl_wrapper.classify_identifier)
for the identifiers given on the command line, for one CIK. Read-only; writes nothing.
Usage (repo root): warehouse\.venv\Scripts\python.exe warehouse\scripts\slice2\classify_ids.py <cik> <id> [<id> ...]"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from pipeline.bdc_xbrl_wrapper import classify_identifier  # noqa: E402

cik = sys.argv[1]
for ident in sys.argv[2:]:
    r = classify_identifier(cik, ident)
    print(ident, "=>", {k: v for k, v in r.items() if v})
