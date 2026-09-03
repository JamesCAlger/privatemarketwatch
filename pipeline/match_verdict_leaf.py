"""Schema validation for match-gold verdict leaves.

Mirrors pipeline/verdict_leaf.py conventions: validator returns a list of
error strings (empty = valid); grounding invariants are hard errors.
"""
from __future__ import annotations

PACKET_VERDICTS = {"CONFIRMED", "WRONG_MERGE", "MISSED_LINK", "MIXED",
                   "INSUFFICIENT_EVIDENCE"}
EDGE_VERDICTS = {"CONFIRMED", "WRONG", "UNCERTAIN"}
_REQUIRED = ["packet_id", "packet_type", "verdict", "confidence", "rationale"]


def _valid_citation(c: dict) -> bool:
    if not isinstance(c, dict):
        return False
    if c.get("quoted_text"):
        return True
    return c.get("table_index") is not None and c.get("row_index") is not None


def validate_match_verdict(doc: dict, *, expected_edges: list[int]) -> list[str]:
    errs: list[str] = []
    for k in _REQUIRED:
        if k not in doc or doc[k] in (None, ""):
            errs.append(f"missing required key: {k}")
    if errs:
        return errs
    if doc["verdict"] not in PACKET_VERDICTS:
        errs.append(f"unknown verdict: {doc['verdict']}")
    try:
        conf = float(doc["confidence"])
        if not 0.0 <= conf <= 1.0:
            errs.append("confidence out of [0,1]")
    except (TypeError, ValueError):
        errs.append("confidence not a number")

    edge_verdicts = doc.get("edge_verdicts") or []
    if doc["packet_type"] == "chain":
        seen = [e.get("edge_index") for e in edge_verdicts]
        if sorted(seen) != sorted(expected_edges):
            errs.append(
                f"edge coverage mismatch: expected {sorted(expected_edges)}, got {sorted(seen)}")
        # Check for duplicate edge_index
        if len(seen) != len(set(seen)):
            for idx in set(seen):
                if seen.count(idx) > 1:
                    errs.append(f"duplicate edge_index: {idx}")
        for e in edge_verdicts:
            if e.get("verdict") not in EDGE_VERDICTS:
                errs.append(f"unknown edge verdict: {e.get('verdict')}")
            if e.get("verdict") == "WRONG":
                if not any(_valid_citation(c) for c in e.get("evidence") or []):
                    errs.append(
                        f"edge {e.get('edge_index')}: WRONG requires a citation")
    elif doc["packet_type"] == "entity":
        if doc["verdict"] == "WRONG_MERGE":
            cites = doc.get("evidence") or []
            if not any(_valid_citation(c) for c in cites):
                errs.append("entity WRONG_MERGE requires a citation")
    else:
        errs.append(f"unknown packet_type: {doc['packet_type']}")

    if doc["verdict"] == "MISSED_LINK":
        links = doc.get("proposed_links") or []
        if not links:
            errs.append("MISSED_LINK requires non-empty proposed_links")
        for ln in links:
            if not any(_valid_citation(c) for c in ln.get("evidence") or []):
                errs.append("proposed link missing citation")
    return errs
