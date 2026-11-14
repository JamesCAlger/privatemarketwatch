"""Exact, page-bound unit-denominated loans approved for the X11 repair.

This is evidence about three source observations, not a loan/unit exemption.
Missing or changed evidence leaves the ordinary missing-principal check active.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re

import duckdb
import pandas as pd
from lxml import html as lhtml

from pipeline import config

EVIDENCE_FILE = config.OVERRIDES_DIR / "source_evidence" / "asif_x11_unit_loans.json"
IDENTITY = ("cik", "report_date", "accession_number", "src_context_id", "row_id")
TEXT = ("issuer_name", "instrument_description")
VALUES = ("shares_held", "fair_value", "cost")


def _normalise(text):
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _page_bound(entry, cache_dir):
    """Verify the pinned page and the exact quote on this context's own table row."""
    path = Path(cache_dir) / str(int(entry["cik"])) / (entry["accession_number"].replace("-", "") + ".html")
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["page_sha256"]:
            return False
        document = lhtml.fromstring(raw)
        nodes = document.xpath("//*[@contextref=$context]", context=entry["src_context_id"])
        if not 1 <= len(nodes) <= 32:
            return False
        quote = _normalise(entry["quote"])
        # Evidence must explicitly disclose this denomination; a share-count tag is insufficient.
        if "Loan instrument units" not in quote or "5,300" not in quote:
            return False
        return any(quote == _normalise(" ".join(row.itertext()))
                   for node in nodes for row in node.xpath("ancestor::tr[1]"))
    except (OSError, ValueError, lhtml.etree.ParserError):
        return False


def verified_row_keys(frame, *, evidence_file=None, cache_dir=None):
    """Return positional row keys with unchanged values and independently bound source evidence."""
    required = set(IDENTITY + TEXT + VALUES) | {"_row_key", "source", "src_facts"}
    if not required.issubset(frame.columns):
        return set()
    path = Path(evidence_file) if evidence_file is not None else EVIDENCE_FILE
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        entries = evidence["entries"]
        if evidence["schema_version"] != "source-unit-loan-evidence.v1" or not 1 <= len(entries) <= 3:
            return set()
        for entry in entries:
            if (entry["cik"] != "0001918712" or entry["shares_held"] != 5300
                    or entry["principal_amount"] is not None
                    or not re.fullmatch(r"0001918712-\d{2}-\d{6}", entry["accession_number"])
                    or not re.fullmatch(r"c-\d+", entry["src_context_id"])
                    or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["report_date"])
                    or not re.fullmatch(r"[0-9a-f]{64}", entry["page_sha256"])):
                return set()
        keys = [tuple(entry[field] for field in IDENTITY) for entry in entries]
        if len(set(keys)) != len(keys):
            return set()
        declared = pd.DataFrame(entries).assign(_evidence_idx=range(len(entries)))
        conditions = ["h.source='bdc'", "TRY_CAST(h.src_facts AS JSON) IS NOT NULL",
                      "json_extract(TRY_CAST(h.src_facts AS JSON),'$.principal_amount.r') IS NULL"]
        conditions += [f"CAST(h.{field} AS VARCHAR)=CAST(e.{field} AS VARCHAR)"
                       for field in IDENTITY + TEXT if field != "report_date"]
        conditions += ["TRY_CAST(h.report_date AS DATE)=TRY_CAST(e.report_date AS DATE)"]
        conditions += [f"TRY_CAST(h.{field} AS DOUBLE)=TRY_CAST(e.{field} AS DOUBLE)" for field in VALUES]
        with duckdb.connect(config={"threads": 2, "memory_limit": "1GB"}) as con:
            con.register("h", frame)
            con.register("e", declared)
            candidates = con.execute("SELECT h._row_key,e._evidence_idx FROM h JOIN e ON "
                                     + " AND ".join(conditions)).fetchall()
        # Only the three configured candidate pages may be parsed, once each per call.
        verified = {index for index in {int(index) for _, index in candidates}
                    if _page_bound(entries[index], cache_dir or config.BDC_HTML_CACHE_DIR)}
        return {int(key) for key, index in candidates if int(index) in verified}
    except (OSError, ValueError, TypeError, KeyError):
        return set()
