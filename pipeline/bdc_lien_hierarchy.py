"""Recover leaf-position lien (and sector) tier from BDC XBRL instance
document order, validated by subtotal reconciliation.

Motivation
----------
Some BDC filers (Blackstone, HPS, Golub, ...) tag the schedule of investments
hierarchically: each individual position fact carries only the
``InvestmentIdentifierAxis`` typed member, while the lien tier
(``...DebtSecuritiesFirstLienMember``) and GICS sector live on *subtotal*
facts.  The leaf and the subtotal therefore live in disjoint dimensional
spaces -- there is no dimensional or calculation-linkbase key joining them.

The only signal is *document order*: in the instance the leaf position facts
are emitted contiguously under their lien x sector subtotal.  This module
walks the fair-value facts in document order, groups each run of leaf
positions, and assigns the lien/sector of the subtotal that closes the run --
**but only accepts the assignment when the leaf run reconciles to the
subtotal value** (derived truth).  Non-reconciling runs are returned flagged,
never silently assigned.

This is read-only (parses cached instances under data/raw/filings/bdc_xbrl).
It does not call the network and does not write production artifacts.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

_FV_CONCEPT = "InvestmentOwnedAtFairValue"

# Reconciliation tolerance: a run is accepted if |leafsum - subtotal| is within
# max(_TOL_ABS, _TOL_PCT * |subtotal|).  Tight on purpose -- this is the gate.
_TOL_PCT = 0.005
_TOL_ABS = 1.0


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _lien_tier(member_localname: str) -> Optional[str]:
    """Map an explicit member local-name to a lien tier, or None."""
    m = member_localname
    if "FirstLien" in m:
        return "First Lien"
    if "SecondLien" in m:
        return "Second Lien"
    if "Unsecured" in m:
        return "Unsecured"
    if "Subordinated" in m or "Mezzanine" in m:
        return "Subordinated"
    return None


def _instrument_type(member_localname: str) -> Optional[str]:
    """Map an explicit member local-name to an instrument type, or None.

    Axis-agnostic, name-based (same philosophy as ``_lien_tier``): a combined
    member like ``FirstLienSeniorSecuredTermLoanMember`` yields BOTH a lien tier
    (via ``_lien_tier``) and an instrument type (here). Rate-index sub-buckets
    (``TermLoanPrimeIndexOneMember``) are EXCLUDED -- they partition term loans by
    reference rate and would double-count against ``TermLoanMember``.
    """
    m = member_localname
    if "Index" in m:                      # rate-index bucket, not an instrument type
        return None
    if "DelayedDraw" in m:
        return "Delayed Draw Term Loan"
    if "Revolv" in m:                     # Revolver / RevolvingLoan / RevolvingCreditFacility
        return "Revolver"
    if "Unitranche" in m:
        return "Unitranche"
    if "TermLoan" in m:
        return "Term Loan"
    return None


@dataclass
class LeafLien:
    issuer: str
    fair_value: float
    lien: Optional[str]
    sector: Optional[str]
    reconciled: bool
    group_id: int


@dataclass
class RecoveryResult:
    period: Optional[str]
    leaves: list[LeafLien] = field(default_factory=list)
    n_leaf_facts: int = 0
    n_sector_subtotals: int = 0
    n_lien_only_subtotals: int = 0
    reconciled_groups: int = 0
    total_groups: int = 0
    recovered_fv: float = 0.0          # FV of leaves with an accepted lien
    flagged_fv: float = 0.0            # FV of leaves in non-reconciling runs
    structure_present: bool = False    # filer uses hierarchical lien tagging

    def lien_split_fv(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for lf in self.leaves:
            key = lf.lien if (lf.lien and lf.reconciled) else "Unknown"
            out[key] = out.get(key, 0.0) + (lf.fair_value or 0.0)
        return out


def parse_instance(xml_path: str):
    """Return (contexts, fv_facts) where contexts maps id->dims and
    fv_facts is the InvestmentOwnedAtFairValue facts in document order."""
    contexts: dict[str, dict] = {}
    facts: list[tuple[str, float]] = []  # (contextRef, value) in document order
    for _ev, el in ET.iterparse(xml_path, events=("end",)):
        tag = _local(el.tag)
        if tag == "context":
            cid = el.get("id")
            lien = sector = issuer = instant = itype = None
            for sub in el.iter():
                st = _local(sub.tag)
                if st == "explicitMember":
                    mln = (sub.text or "").strip().rsplit(":", 1)[-1]
                    t = _lien_tier(mln)
                    if t:
                        lien = t
                    it = _instrument_type(mln)
                    if it:
                        itype = it
                    if not t and not it and ("Sector" in mln or "Industry" in mln):
                        sector = mln
                elif st == "typedMember":
                    dim = sub.get("dimension") or ""
                    if "Investment" in dim:
                        kids = list(sub)
                        issuer = ((kids[0].text if kids else sub.text) or "").strip()
                elif st == "instant":
                    instant = (sub.text or "").strip()
            contexts[cid] = {"lien": lien, "sector": sector, "issuer": issuer,
                             "instant": instant, "itype": itype}
            el.clear()
        elif el.get("contextRef") is not None and tag == _FV_CONCEPT:
            txt = (el.text or "").replace(",", "").strip()
            if txt not in ("", "-"):
                try:
                    facts.append((el.get("contextRef"), float(Decimal(txt))))
                except (InvalidOperation, ValueError):
                    pass
            el.clear()
    return contexts, facts


def recover_lien(contexts: dict, facts: list, period: Optional[str] = None) -> RecoveryResult:
    """Group leaf runs by document order, accept lien only when the run
    reconciles to the closing lien x sector subtotal."""
    from collections import Counter

    if period is None:
        inst = Counter(contexts.get(c, {}).get("instant")
                       for c, _ in facts
                       if contexts.get(c, {}).get("issuer")
                       and contexts.get(c, {}).get("instant"))
        period = inst.most_common(1)[0][0] if inst else None

    res = RecoveryResult(period=period)
    run: list[tuple[str, float]] = []   # (issuer, fv) leaves in current run
    run_sum = 0.0
    gid = 0
    sector_subtotals = 0
    lien_only_subtotals = 0

    def _close(ctx, val, run, run_sum, gid):
        """Validate a leaf run against a lien-bearing subtotal and append."""
        ok = abs(run_sum - val) <= max(_TOL_ABS, _TOL_PCT * abs(val))
        for iss, fv in run:
            res.leaves.append(LeafLien(iss, fv, ctx["lien"], ctx.get("sector"), ok, gid))
        res.total_groups += 1
        if ok:
            res.reconciled_groups += 1
            res.recovered_fv += run_sum
        else:
            res.flagged_fv += run_sum
        return ok

    def classify(cid):
        ctx = contexts.get(cid, {})
        if ctx.get("instant") != period:
            return "skip", ctx
        if ctx.get("issuer") and not ctx.get("lien"):
            return "leaf", ctx
        if ctx.get("lien") and ctx.get("sector"):
            return "lien_sector", ctx
        if ctx.get("lien"):
            return "lien_only", ctx
        return "other", ctx

    for cid, val in facts:
        kind, ctx = classify(cid)
        if kind == "skip":
            continue
        if kind == "leaf":
            res.n_leaf_facts += 1
            run.append((ctx.get("issuer"), val))
            run_sum += val
        else:
            # any non-leaf FV fact is a boundary; lien-bearing subtotals validate
            if kind == "lien_sector":
                sector_subtotals += 1
                if run:
                    _close(ctx, val, run, run_sum, gid); gid += 1
            elif kind == "lien_only":
                lien_only_subtotals += 1
                if run:
                    _close(ctx, val, run, run_sum, gid); gid += 1
            else:
                # grand total / equity block -> flush unassigned
                for iss, fv in run:
                    res.leaves.append(LeafLien(iss, fv, None, None, False, gid))
                if run:
                    res.flagged_fv += run_sum
                    res.total_groups += 1
                    gid += 1
            run = []
            run_sum = 0.0

    # trailing leaves with no closing subtotal
    for iss, fv in run:
        res.leaves.append(LeafLien(iss, fv, None, None, False, gid))
    if run:
        res.flagged_fv += run_sum
        res.total_groups += 1

    res.n_sector_subtotals = sector_subtotals
    res.n_lien_only_subtotals = lien_only_subtotals
    res.structure_present = (sector_subtotals + lien_only_subtotals) > 0 and res.n_leaf_facts > 0
    return res


def extract_lien_for_filing(xml_path: str, period: Optional[str] = None) -> RecoveryResult:
    contexts, facts = parse_instance(xml_path)
    return recover_lien(contexts, facts, period=period)


# ---------------------------------------------------------------------------
# Per-position instrument-type recovery (revolver / DDTL / term loan / unitranche)
# ---------------------------------------------------------------------------
# Lifts per-position instrument_type for filers that tag the type on XBRL
# SUBTOTAL members (e.g. Ares) rather than in the row text the keyword classifier
# reads.  Two sources, both high-confidence:
#   1. DIRECT: a leaf (issuer) context that itself carries a type member.
#   2. RECOVERED: a contiguous run of typeless leaf FV facts that is immediately
#      closed by a type-bearing subtotal it RECONCILES to (same gate as lien).
# Conservative by design: a typeless run gets a type ONLY when a type subtotal
# directly closes it AND the arithmetic reconciles; any non-type boundary
# (lien-only subtotal, grand total) flushes the run untyped.


def recover_instrument_type(
    contexts: dict, facts: list, period: Optional[str] = None
) -> list[tuple[str, float, Optional[str], bool]]:
    """Return [(issuer_identifier, fair_value, instrument_type|None, reconciled)]."""
    from collections import Counter

    if period is None:
        inst = Counter(contexts.get(c, {}).get("instant")
                       for c, _ in facts
                       if contexts.get(c, {}).get("issuer")
                       and contexts.get(c, {}).get("instant"))
        period = inst.most_common(1)[0][0] if inst else None

    out: list[tuple[str, float, Optional[str], bool]] = []
    run: list[tuple[str, float]] = []
    run_sum = 0.0

    def _close(itype: str, val: float) -> None:
        ok = abs(run_sum - val) <= max(_TOL_ABS, _TOL_PCT * abs(val))
        for ident, fv in run:
            out.append((ident, fv, itype if ok else None, ok))

    def _flush() -> None:
        for ident, fv in run:
            out.append((ident, fv, None, False))

    for cid, val in facts:
        ctx = contexts.get(cid, {})
        if ctx.get("instant") != period:
            continue
        issuer = ctx.get("issuer")
        itype = ctx.get("itype")
        if issuer:
            if itype:                       # leaf tagged with its own type -> direct
                out.append((issuer, val, itype, True))
            else:
                run.append((issuer, val))
                run_sum += val
        else:                               # subtotal / boundary
            if run:
                if itype:
                    _close(itype, val)
                else:
                    _flush()
                run = []
                run_sum = 0.0
    if run:
        _flush()
    return out


def extract_instrument_type_positions(xml_path: str, period: Optional[str] = None):
    contexts, facts = parse_instance(xml_path)
    return recover_instrument_type(contexts, facts, period=period)
