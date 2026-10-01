"""Census-side published-basis partition predicate (census-published.v1). Pure functions, no I/O.

Seven ordered rules from the 2026-10-01 investigation (scratch/2026-10-01_census_published_basis,
reference implementation s21_predicate_v2.py) that reconcile the eight pilot filers' census positions
to production's published basis within 0.5%. R1-R5 remove a position; R6 marks it underlying (not
published); R7 adds cash-equivalent-axis fair-value facts the census does not treat as positions.
The first rule that fires wins.

Final-review hardening (2026-10-01): with no period end (neither the DEI fact nor
document_period_end_dates) classify reports period_end=None and no_period_end=True, R1 fails closed
(every row is removed) and R7 emits nothing, so consumers must abstain (contracts_totals does, with cause
no_period_end). `near_misses` counts the FV-only parents that are a token prefix of >= 1 kept rows but fail
the R5 children-sum equality (rollups that would slip back into the sum stay visible). R7 needs every
InvestmentOwnedAtFairValue fact of a qualifying context to agree; a disagreeing context is skipped and
listed in `r7_conflicts` instead of taking the first fact in document order.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

CENSUS_PUBLISHED_VERSION = "census-published.v1"
REPORTING_ENTITIES = {"0001803498": ("Emerald JV LP", "Verdelite JV LP")}   # R6 list per filer (v1 data)
RULES = ("R1_own_period_instant", "R2_fv_not_reported", "R3_label_or_heading", "R4_generic_cash_bucket",
         "R5_issuer_rollup_fv_only", "R6_reporting_entity_lookthrough")
R7_SOURCE = "R7_cash_equivalent_axis"

LABEL_SEGMENT = re.compile(r"^(sub-?\s*)?total\b|^net assets$")
CATEGORY_HEADING = re.compile(r"^(non-?)?controlled[\s,/-]*(non-?)?affiliated investments$")
CASH_BUCKET = re.compile(r"^(other )?cash and cash equivalents\b")
REPORTED = ("reported", "consistent_duplicate")


def _segments(ident):
    return [s.strip().lower() for s in (ident or "").split("|")] if ident else []


def _norm(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _dec(value):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _fv(pos):
    return _dec(pos["fields"].get("fair_value", {}).get("value"))


def period_end(doc):
    """(date, source): the dei:DocumentPeriodEndDate fact value, else max(document_period_end_dates)."""
    vals = sorted({str(f.get("value")).strip() for f in doc.get("facts", ())
                   if f.get("qname") == "dei:DocumentPeriodEndDate" and f.get("value")})
    if vals:
        return vals[-1], "dei:DocumentPeriodEndDate"
    dates = (doc.get("document_metadata") or {}).get("document_period_end_dates") or []
    return (max(dates), "document_metadata.max") if dates else (None, "none")


def r1_own_period_instant(pos, pe):
    return (pos.get("period") or {}).get("instant") != pe


def r2_fv_not_reported(pos):
    return pos["fields"].get("fair_value", {}).get("value") in (None, "")


def r3_label_or_heading(pos):
    return any(LABEL_SEGMENT.search(s) or CATEGORY_HEADING.match(" ".join(s.split()))
               for s in _segments(pos["identity"].get("typed_identifier")))


def r4_generic_cash_bucket(pos):
    segs = _segments(pos["identity"].get("typed_identifier"))
    shares = pos["fields"].get("shares_held", {}).get("status") in REPORTED
    if any("money market" in s or ("fund" in s and shares) for s in segs):
        return False
    return any(CASH_BUCKET.match(s) for s in segs)


def _fv_only(pos):
    f = pos["fields"]
    return (f.get("fair_value", {}).get("status") == "reported"
            and sum(1 for v in f.values() if v.get("status") == "reported") == 1)


def _r5_scan(live):
    """(rollups, near_misses): context ids of FV-only rows whose normalised identifier is a token prefix of
    >=1 other live rows and whose FV equals their FV sum within half a unit of the reported decimals per
    summand (min 1); near_misses are the same prefix parents that FAIL that equality."""
    keys = [(_norm(p["identity"].get("typed_identifier")), p) for p in live]
    out, near = set(), []
    for key, parent in keys:
        if not key or not _fv_only(parent):
            continue
        kids = [p for k, p in keys if p is not parent and k.startswith(key + " ")]
        if not kids:
            continue
        try:
            d = int(parent["fields"]["fair_value"].get("decimals"))
        except (TypeError, ValueError):
            d = 0
        tol = max(Decimal("0.5") * Decimal(10) ** (-d) * (len(kids) + 1), Decimal(1))
        if abs((_fv(parent) or Decimal(0)) - sum((_fv(k) or Decimal(0) for k in kids), Decimal(0))) <= tol:
            out.add(parent["context_id"])
        else:
            near.append(parent)
    return out, near


def r5_issuer_rollups(live):
    """Context ids of the R5 rollups (see _r5_scan)."""
    return _r5_scan(live)[0]


def r6_reporting_entity(pos, cik):
    names = {_norm(n) for n in REPORTING_ENTITIES.get(cik, ())}
    return bool(names) and any(_norm(s) in names for s in _segments(pos["identity"].get("typed_identifier"))[1:])


def _r7_scan(doc, pe):
    """(facts, conflicts): one fact per qualifying context whose InvestmentOwnedAtFairValue facts all agree;
    contexts whose facts disagree are skipped and returned as conflicts. No period end -> nothing."""
    if pe is None:
        return [], []
    held = {p["context_id"] for p in doc.get("positions", ())}
    ctxs = {c["id"]: c for c in doc.get("contexts", ())
            if (c.get("period") or {}).get("instant") == pe and c["id"] not in held
            and not c.get("typed_dimensions") and len(c.get("dimensions") or ()) == 1
            and str(c["dimensions"][0][0]).endswith("CashAndCashEquivalentsAxis")}
    values = {}
    for f in doc.get("facts", ()):
        cid = f.get("context_id")
        if cid in ctxs and f.get("qname") == "us-gaap:InvestmentOwnedAtFairValue":
            v = _dec(f.get("value"))
            if v is not None:
                values.setdefault(cid, []).append(v)
    out, conflicts = [], []
    for cid, vs in values.items():
        if len(set(vs)) == 1:
            out.append(dict(context_id=cid, fair_value=vs[0], source=R7_SOURCE))
        else:
            conflicts.append(dict(context_id=cid, values=[str(v) for v in vs]))
    return out, conflicts


def r7_cash_axis_facts(doc, pe):
    return _r7_scan(doc, pe)[0]


def classify(doc, *, cik):
    pe, pe_source = period_end(doc)
    rows, live = {}, []
    for pos in doc.get("positions", ()):
        rule = ("R1_own_period_instant" if r1_own_period_instant(pos, pe) else
                "R2_fv_not_reported" if r2_fv_not_reported(pos) else
                "R3_label_or_heading" if r3_label_or_heading(pos) else
                "R4_generic_cash_bucket" if r4_generic_cash_bucket(pos) else None)
        rows[pos["context_id"]] = rule
        if rule is None:
            live.append(pos)
    rollups, near = _r5_scan(live)
    for cid in rollups:
        rows[cid] = "R5_issuer_rollup_fv_only"
    for pos in live:
        if rows[pos["context_id"]] is None and r6_reporting_entity(pos, cik):
            rows[pos["context_id"]] = "R6_reporting_entity_lookthrough"
    removed = {r: {"n": 0, "fv": Decimal(0)} for r in RULES}
    for pos in doc.get("positions", ()):
        rule = rows[pos["context_id"]]
        if rule:
            removed[rule]["n"] += 1
            removed[rule]["fv"] += _fv(pos) or Decimal(0)
    r7, r7_conflicts = _r7_scan(doc, pe)
    return {"version": CENSUS_PUBLISHED_VERSION, "period_end": pe, "period_end_source": pe_source,
            "no_period_end": pe is None,
            "rows": {c: {"published": r is None, "underlying": r == "R6_reporting_entity_lookthrough", "rule": r}
                     for c, r in rows.items()},
            "extra_fv_facts": [dict(f, fair_value=float(f["fair_value"])) for f in r7],
            "r7_conflicts": r7_conflicts,
            "near_misses": {"n": len(near), "fv": float(sum((_fv(p) or Decimal(0) for p in near), Decimal(0)))},
            "removed_by_rule": {r: {"n": v["n"], "fv": float(v["fv"])} for r, v in removed.items()}}


def published_positions(doc, *, cik):
    rows = classify(doc, cik=cik)["rows"]
    return [p for p in doc.get("positions", ()) if rows[p["context_id"]]["published"]]


def published_fv_sum(doc, *, cik):
    out = classify(doc, cik=cik)
    total = sum((_fv(p) or Decimal(0) for p in doc.get("positions", ()) if out["rows"][p["context_id"]]["published"]),
                Decimal(0))
    return total + sum((f["fair_value"] for f in r7_cash_axis_facts(doc, out["period_end"])), Decimal(0))
