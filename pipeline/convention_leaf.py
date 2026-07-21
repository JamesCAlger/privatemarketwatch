"""Convention leaf: the one auditable JSON the Convention Adjudicator writes.

The Convention Adjudicator is an anchor-shaped agent (per-CIK FACT -> promoted
override), NOT a B1-shaped flag adjudicator. Its sole job: decide from the
FILING whether the filer's stated position-level interest_rate is the ALL-IN
coupon (PIK included) or the CASH leg only (PIK on top). It does not modify
holdings and never sees the deterministic classifier's signals (the prompt is
blind by design); its verdict is only accepted after the deterministic
cross-checks in ``pipeline.convention_validation`` -- citation reconciliation
against the stored rates and the signal-contradiction gate -- which the worker
cannot influence.

Leaf (one JSON object)::

    {"cik": "1812554", "target_quarter": "2025-12-31",
     "convention": "all_in",              # all_in | cash_leg | indeterminate
     "column_semantics": "single 'Interest Rate' column; PIK parenthetical",
     "citations": [
       {"kind": "header",   "quote": "Interest Rate (2)", "where": "SOI p.12"},
       {"kind": "footnote", "quote": "(2) Includes paid-in-kind interest ...",
        "where": "SOI notes"},
       {"kind": "position", "issuer": "Acme Corp",
        "quote": "12.50% (incl. 3.00% PIK)",
        "printed_total": 12.50, "printed_pik": 3.00}],
     "applies_from": "2022-03-31",
     "rationale": "...", "confidence": 0.9}

A DECIDED leaf (all_in / cash_leg) requires >= 2 ``position`` citations, each
carrying ``issuer``, ``quote``, a numeric ``printed_pik``, and a numeric
``printed_total`` or ``printed_cash`` -- these feed the reconciliation check.
A header/footnote citation is strongly recommended; its absence caps the
verify tier at MEDIUM (convention_validation), it is not a schema error.
An INDETERMINATE leaf instead requires a non-empty ``search_trail`` (what was
checked and found silent). ASCII-only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REQUIRED = ("cik", "target_quarter", "convention", "citations", "rationale", "confidence")
CONVENTIONS = frozenset({"all_in", "cash_leg", "indeterminate"})
CITATION_KINDS = frozenset({"header", "footnote", "position", "text"})
MIN_POSITION_CITATIONS = 2
_CIK_RE = re.compile(r"^\d{1,10}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def load_convention_leaf(path: Path) -> dict | None:
    """Read a leaf JSON (utf-8-sig: sandbox workers write BOMs). None if unreadable."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _position_citation_errors(c: dict, i: int) -> list[str]:
    errs = []
    if not str(c.get("issuer") or "").strip():
        errs.append(f"citations[{i}]: position citation needs a non-empty issuer")
    if not _is_num(c.get("printed_pik")):
        errs.append(f"citations[{i}]: position citation needs numeric printed_pik")
    if not (_is_num(c.get("printed_total")) or _is_num(c.get("printed_cash"))):
        errs.append(f"citations[{i}]: position citation needs numeric printed_total or printed_cash")
    return errs


def validate_convention_leaf(leaf: dict) -> list[str]:
    """Schema errors (empty list = valid). Pure; no IO."""
    errs: list[str] = []
    if not isinstance(leaf, dict):
        return ["leaf is not a JSON object"]
    for k in REQUIRED:
        if k not in leaf:
            errs.append(f"missing required field: {k}")
    if errs:
        return errs

    if not _CIK_RE.match(str(leaf.get("cik") or "")):
        errs.append("cik must be 1-10 digits")
    if not _DATE_RE.match(str(leaf.get("target_quarter") or "")):
        errs.append("target_quarter must be YYYY-MM-DD")
    conv = leaf.get("convention")
    if conv not in CONVENTIONS:
        errs.append(f"convention must be one of {sorted(CONVENTIONS)}")
    conf = leaf.get("confidence")
    if not (_is_num(conf) and 0.0 <= float(conf) <= 1.0):
        errs.append("confidence must be a number in [0, 1]")
    if not str(leaf.get("rationale") or "").strip():
        errs.append("rationale must be non-empty")
    af = leaf.get("applies_from")
    if af is not None and not _DATE_RE.match(str(af)):
        errs.append("applies_from must be YYYY-MM-DD when present")

    cits = leaf.get("citations")
    if not isinstance(cits, list):
        errs.append("citations must be a list")
        cits = []
    n_position = 0
    for i, c in enumerate(cits):
        if not isinstance(c, dict):
            errs.append(f"citations[{i}] is not an object")
            continue
        kind = c.get("kind")
        if kind not in CITATION_KINDS:
            errs.append(f"citations[{i}]: kind must be one of {sorted(CITATION_KINDS)}")
        if not str(c.get("quote") or "").strip():
            errs.append(f"citations[{i}]: quote must be non-empty")
        if kind == "position":
            n_position += 1
            errs.extend(_position_citation_errors(c, i))

    if conv in ("all_in", "cash_leg"):
        if n_position < MIN_POSITION_CITATIONS:
            errs.append(f"decided verdict requires >= {MIN_POSITION_CITATIONS} position "
                        f"citations (got {n_position})")
    elif conv == "indeterminate":
        trail = leaf.get("search_trail")
        if not (isinstance(trail, list) and trail
                and all(str(t or "").strip() for t in trail)):
            errs.append("indeterminate verdict requires a non-empty search_trail "
                        "(list of what was checked)")
    return errs
