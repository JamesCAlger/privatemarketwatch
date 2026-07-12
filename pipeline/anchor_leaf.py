"""Anchor leaf: the one auditable JSON the anchor-adjudicator agent writes.

The anchor-adjudicator is a SEPARATE agent from the B2 fixer (a B1-style independent pre-pass). Its
sole job: find the filer's GRAND total of investments at fair value -- wherever it lives, because the
location is filer-idiosyncratic (a single undimensioned us-gaap tag; the last "Total Investments" row
of one SOI; or the SUM of several affiliation-class schedule subtotals when there is no single grand-
total row). It reports the number it found, the METHOD, and a CITED component for each piece. It does
NOT author holdings fixes (separation = it cannot grade the fixer's homework), and its number is only
accepted after the deterministic balance-sheet CLOSURE check in ``pipeline.anchor_validation`` (the
agent does not control total_assets/cash, so it cannot fabricate a closing total).

Leaf (one JSON object)::

    {"cik": "1715933", "target_quarter": "2025-06-30",
     "grand_total": 1094088266.0,
     "method": "sum_of_schedules",                       # single_tag | total_row | sum_of_schedules
     "components": [
       {"label": "non-affiliated", "value": 691956192.0, "source": "companyfacts InvestmentOwnedAtFairValue"},
       {"label": "affiliated",     "value": 402132074.0, "source": "SOI affiliated schedule total row (p.47)"}],
     "companyfacts_fv": 691956192.0,                     # the original (possibly incomplete) tag
     "evidence": [{"source": "filing", "quote": "Total ... 1,094,088"}],
     "rationale": "companyfacts tag captures only the non-affiliated schedule; ...",
     "confidence": 0.9}

ASCII-only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REQUIRED = ("cik", "target_quarter", "grand_total", "method", "components", "evidence", "confidence")
METHODS = frozenset({"single_tag", "total_row", "sum_of_schedules"})
_CIK_RE = re.compile(r"^\d{1,10}$")
_SUM_TOL = 0.01    # components must sum to grand_total within 1% (sum_of_schedules)


def _is_pos_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and float(x) > 0


def validate_anchor_leaf(obj) -> list[str]:
    """Return reasons the anchor leaf is invalid (empty list = schema-valid). This validates SHAPE +
    internal consistency only; the balance-sheet closure check (the un-gameable part) is separate
    (anchor_validation.verify_grand_total)."""
    errs: list[str] = []
    if not isinstance(obj, dict):
        return ["anchor leaf is not a JSON object"]
    for k in REQUIRED:
        if k not in obj:
            errs.append(f"missing required key: {k}")
    if not _CIK_RE.match(str(obj.get("cik") or "").strip()):
        errs.append(f"cik must be 1-10 digits, got {obj.get('cik')!r}")
    if not str(obj.get("target_quarter") or "").strip():
        errs.append("target_quarter is empty")
    if not _is_pos_num(obj.get("grand_total")):
        errs.append("grand_total must be a positive number")
    if str(obj.get("method")) not in METHODS:
        errs.append(f"method must be one of {sorted(METHODS)}, got {obj.get('method')!r}")

    comps = obj.get("components")
    if not isinstance(comps, list) or not comps:
        errs.append("components must be a non-empty list")
    else:
        for i, c in enumerate(comps):
            if not isinstance(c, dict):
                errs.append(f"components[{i}] must be an object"); continue
            if not str(c.get("label") or "").strip():
                errs.append(f"components[{i}] missing label")
            if not _is_pos_num(c.get("value")):
                errs.append(f"components[{i}].value must be a positive number")
            if not str(c.get("source") or "").strip():
                errs.append(f"components[{i}] missing source (cite where it came from)")
        # sum_of_schedules MUST reconcile to grand_total (deterministic internal consistency).
        if str(obj.get("method")) == "sum_of_schedules" and _is_pos_num(obj.get("grand_total")) \
                and all(_is_pos_num(c.get("value")) for c in comps if isinstance(c, dict)):
            s = sum(float(c["value"]) for c in comps)
            g = float(obj["grand_total"])
            if abs(s - g) > _SUM_TOL * g:
                errs.append(f"sum_of_schedules components sum to {s:.0f} but grand_total is {g:.0f} "
                            f"(>{_SUM_TOL*100:.0f}% apart) -- they must reconcile")

    if not isinstance(obj.get("evidence"), list) or not obj.get("evidence"):
        errs.append("evidence must be a non-empty list")
    conf = obj.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0.0 <= float(conf) <= 1.0):
        errs.append("confidence must be a number in [0,1]")
    # OPTIONAL filing-sourced total_assets (for a companyfacts-lagged quarter): lets the closure
    # check run off the filing's own balance sheet. If given, it MUST cite the balance-sheet line.
    ta = obj.get("total_assets")
    if ta is not None:
        if not _is_pos_num(ta):
            errs.append("total_assets, if given, must be a positive number")
        if not str(obj.get("total_assets_source") or "").strip():
            errs.append("total_assets requires total_assets_source (cite the balance-sheet line)")
    return errs


def load_anchor_leaf(path) -> dict | None:
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
