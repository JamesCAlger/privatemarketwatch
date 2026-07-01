"""Anchor validation: is the conservation anchor itself TRUE before the loop reconciles to it?

The agentic investigation loop (agent_rule + run_investigation) drives the fund-quarter
``value_sum`` toward an ANCHOR. That only produces correct corrections if the anchor is a true,
independent measure of the portfolio fair value. If the anchor is wrong, an apply-and-measure
loop becomes a reconciliation MAXIMIZER that delete-to-balances against a false number -- the
1743415 failure (a $406M schedule "reconciled" to a mis-extracted $13.96M anchor by deleting
97%). So before the loop is allowed to trust the residual, the anchor must be validated.

The principle is INDEPENDENCE, and the crucial distinction is between a separate MEASUREMENT and a
re-aggregation of the extraction under test:

  STRONG (an independent measurement -- usable to validate the anchor):
    ``companyfacts_fv``        -- the XBRL-tagged fund-level total investments at fair value
                                  (us-gaap concept, undimensioned).
    ``companyfacts_concept`` / ``cf_cache_cost`` / ``ff_investments_at_cost``
                               -- other XBRL-tagged fund-level totals (cost-side; not
                                  interchangeable with FV, but independent measurements).
    ``printed_schedule_total`` -- the filer's OWN PRINTED schedule total, read from the filing
                                  (evidence_cli ``totals``). Not yet wired structurally; wiring it
                                  is the path to a HIGH FV tier.

  EXTRACTION RE-SUM (NOT usable to validate the anchor):
    ``schedule_total`` (this repo's existing one), ``value_sum``, ``extract_total_fv`` -- all are
    re-aggregations of the SAME extracted rows. Their disagreement with a strong anchor is the
    DEFECT WE ARE FIXING, not evidence about anchor validity. Comparing the anchor to a re-sum
    would make the gate escalate on exactly the CIKs that have a real defect -- backwards. So a
    re-sum is NEVER the agreement partner and NEVER the consensus value.

Two independent checks:

  1. ``classify_anchors`` -- the pairwise agreement test among STRONG anchors for ONE quarter:
       HIGH    >= 2 strong anchors AGREE within tol  -> residual well-defined; loop may run.
       MEDIUM  exactly 1 strong anchor               -> single-sourced; loop may run, but a partial
                                                        residual is a signal, not a target to grind.
       NONE    0 strong anchors, OR >= 2 strong DISAGREE -> escalate; do NOT reconcile.
     (HIGH needs a second independent measurement, e.g. printed_schedule_total. Today, with only
     companyfacts_fv wired, the ceiling is MEDIUM -- which is why check 2 matters.)

  2. ``flag_anchor_outliers`` -- cross-quarter plausibility on a CIK's companyfacts series. A
     single quarter's tagged total wildly out of line with the CIK's OWN other quarters is itself
     suspect -- companyfacts vs companyfacts over time, independent of the extraction. This catches
     a SPORADIC anchor mis-extraction (one bad quarter among good ones). It does NOT catch a
     SYSTEMATICALLY mis-tagged anchor -- one that is consistently wrong every quarter (e.g. CIK
     1743415, whose companyfacts FV tag reads ~$14-28M across all 4 covered quarters while the
     extraction is a smooth ~$180-514M over 11 quarters: the TAG is broken, not the holdings).
     A self-consistent-but-wrong series has no good quarter to deviate from, so only a SECOND
     INDEPENDENT anchor (printed_schedule_total -> HIGH) can expose it. A flagged quarter's anchor
     is dropped to NONE upstream.

Pure, dependency-light (no IO). The caller assembles candidates (see
scripts/agent_investigate/run_investigation.load_anchor_candidates) and passes them to
``gate_rules`` so the held-out gate refuses to PASS a reconciliation against a NONE anchor.

ASCII-only.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

# Anchors that are an INDEPENDENT MEASUREMENT (usable to validate the anchor). Anything not in
# this set -- including the extraction re-sums (schedule_total/value_sum/extract_total_fv) and any
# unrecognised name -- is ignored by the agreement test (cannot fake a strong anchor via a typo).
STRONG_ANCHORS = frozenset({
    "companyfacts_fv", "companyfacts_concept", "cf_cache_cost", "ff_investments_at_cost",
    "printed_schedule_total",
})

DEFAULT_AGREE_TOL = 0.01    # 1% -- "are these the same quantity", looser than the reconcile band
DEFAULT_OUTLIER_FOLD = 3.0  # cross-quarter: flag a companyfacts total >3x or <1/3 the CIK median
MIN_OUTLIER_HISTORY = 3     # need at least this many quarters to judge an outlier

HIGH, MEDIUM, NONE = "HIGH", "MEDIUM", "NONE"


@dataclass
class AnchorVerdict:
    """The validation outcome for ONE quarter's anchor candidates."""
    tier: str = NONE
    consensus: float | None = None          # value the loop may reconcile to (a STRONG anchor); None if NONE
    reason: str = ""
    strong: dict[str, float] = field(default_factory=dict)
    max_disagreement: float | None = None   # max pairwise relative spread among the strong anchors

    @property
    def may_reconcile(self) -> bool:
        return self.tier in (HIGH, MEDIUM) and self.consensus is not None


def _strong(candidates) -> dict[str, float]:
    """Keep only STRONG, positive anchor values."""
    out: dict[str, float] = {}
    for name, val in (candidates or {}).items():
        if str(name) not in STRONG_ANCHORS:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[str(name)] = v
    return out


def _rel_spread(values) -> float:
    vals = [abs(v) for v in values if v]
    if len(vals) < 2:
        return 0.0
    hi, lo = max(vals), min(vals)
    return (hi - lo) / hi if hi else 0.0


def classify_anchors(candidates, *, agree_tol: float = DEFAULT_AGREE_TOL) -> AnchorVerdict:
    """Classify one quarter's candidates into a tier + consensus value, using STRONG anchors only.

    ``candidates``: {anchor_name -> value}. Extraction re-sums and unknown names are ignored.
    """
    strong = _strong(candidates)

    if not strong:
        return AnchorVerdict(tier=NONE, consensus=None, strong=strong,
                             reason=("no independent anchor available (only the extraction re-sum, "
                                     "which is the quantity under test) -- cannot validate, escalate"))

    if len(strong) == 1:
        (name, val), = strong.items()
        return AnchorVerdict(tier=MEDIUM, consensus=val, strong=strong,
                             reason=(f"single independent anchor {name}={val:.0f}; loop may run but "
                                     f"the anchor is single-sourced -- a partial residual is a signal, "
                                     f"not a target. (HIGH needs a 2nd independent measurement.)"))

    spread = _rel_spread(strong.values())
    if spread <= agree_tol:
        return AnchorVerdict(tier=HIGH, consensus=sum(strong.values()) / len(strong), strong=strong,
                             max_disagreement=spread,
                             reason=(f"{len(strong)} independent anchors agree within "
                                     f"{agree_tol*100:.2g}% ({_fmt(strong)})"))
    return AnchorVerdict(tier=NONE, consensus=None, strong=strong, max_disagreement=spread,
                         reason=(f"independent anchors DISAGREE by {spread*100:.1f}% "
                                 f"({_fmt(strong)}); residual undefined -- escalate, do not "
                                 f"reconcile to either"))


@dataclass
class OutlierFlag:
    flagged: bool = False
    reason: str = ""
    ratio: float | None = None      # value / median


def flag_anchor_outliers(series, *, fold: float = DEFAULT_OUTLIER_FOLD,
                         min_history: int = MIN_OUTLIER_HISTORY) -> dict[str, OutlierFlag]:
    """Cross-quarter plausibility on a CIK's companyfacts total series {quarter -> value}.

    A quarter whose value is > ``fold`` x or < 1/``fold`` x the CIK's MEDIAN is flagged as a
    suspect (likely mis-extracted) anchor. Catches a SPORADIC mis-extraction (one quarter off its
    neighbors); a SYSTEMATICALLY wrong tag (every quarter wrong by the same factor) is self-
    consistent here and needs a second independent anchor instead. Independent of the line-item
    extraction (companyfacts vs companyfacts over time). With fewer than ``min_history`` usable
    quarters there is no basis to judge -> nothing flagged.
    """
    usable = {str(q): float(v) for q, v in (series or {}).items()
              if _is_pos(v)}
    out: dict[str, OutlierFlag] = {q: OutlierFlag() for q in usable}
    if len(usable) < min_history:
        return out
    med = statistics.median(usable.values())
    if med <= 0:
        return out
    for q, v in usable.items():
        ratio = v / med
        if ratio > fold or ratio < 1.0 / fold:
            out[q] = OutlierFlag(
                flagged=True, ratio=round(ratio, 3),
                reason=(f"companyfacts total {v:.0f} is {ratio:.2g}x the CIK median {med:.0f} "
                        f"(outside {1/fold:.2g}x-{fold:.2g}x) -- likely a mis-extracted anchor; "
                        f"escalate, do not reconcile to it"))
    return out


def _is_pos(v) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def _fmt(d: dict[str, float]) -> str:
    return ", ".join(f"{n}={v:.0f}" for n, v in sorted(d.items()))


def classify_many(candidates_by_quarter, *, agree_tol: float = DEFAULT_AGREE_TOL):
    """Classify each quarter -> AnchorVerdict."""
    return {str(q): classify_anchors(c, agree_tol=agree_tol)
            for q, c in (candidates_by_quarter or {}).items()}


# --- anchor-adjudicator: verify an agent-found GRAND total against the balance sheet -----------
# The anchor-finder agent reports a grand_total; this is the un-gameable check on it. The agent does
# NOT control total_assets/cash (independent balance-sheet facts), so it cannot fabricate a number
# that CLOSES. A BDC's investments are a large fraction of total assets, bounded above by total
# assets and below by the (possibly partial) companyfacts tag.
ASSET_TOL = 0.01          # grand_total may not exceed total_assets beyond this
FLOOR_TOL = 0.01          # grand_total may not fall below the companyfacts tag beyond this
CLOSE_TOL = 0.03          # with cash known: |total_assets - grand_total - cash| within this*assets = tight
INVESTED_FLOOR = 0.80     # BDCs run >= ~80% invested; below this an "anchor" looks like a subtotal
VERIFY_OTHER_CEILING = 0.15   # with cash known, a non-cash remainder above this = a missing schedule


@dataclass
class GrandTotalCheck:
    tier: str = NONE
    reasons: list[str] = field(default_factory=list)
    invested_frac: float | None = None      # grand_total / total_assets
    implied_other: float | None = None       # total_assets - grand_total - cash (if cash known)

    @property
    def ok(self) -> bool:
        return self.tier in (HIGH, MEDIUM)


def verify_grand_total(grand_total, *, total_assets, companyfacts_fv=None, cash=None,
                       invested_floor: float = INVESTED_FLOOR) -> GrandTotalCheck:
    """Verify an agent-found grand total of investments at fair value against the balance sheet.

    Hard-fail (NONE): exceeds total_assets, falls below the companyfacts tag, or investments+cash
    exceed total_assets -- each is physically impossible. Otherwise tier on CLOSURE quality: HIGH
    when it closes tightly (cash known and total_assets-grand_total-cash is ~0, or invested fraction
    is high), MEDIUM when plausible but uncorroborated.
    """
    r = GrandTotalCheck()
    try:
        g = float(grand_total); ta = float(total_assets)
    except (TypeError, ValueError):
        r.reasons.append("grand_total/total_assets not numeric"); return r
    if not (g > 0 and ta > 0):
        r.reasons.append("grand_total and total_assets must be positive"); return r

    r.invested_frac = round(g / ta, 4)
    # --- hard bounds ---
    if g > ta * (1 + ASSET_TOL):
        r.reasons.append(f"grand_total {g:.0f} exceeds total_assets {ta:.0f} -- impossible")
        return r
    if companyfacts_fv and g < float(companyfacts_fv) * (1 - FLOOR_TOL):
        r.reasons.append(f"grand_total {g:.0f} is below the companyfacts tag {float(companyfacts_fv):.0f} "
                         f"(the tag is a floor) -- wrong")
        return r
    if cash is not None:
        try:
            c = float(cash)
            # g > total_assets is already rejected above, so if g + cash now exceeds assets the cash
            # is ALREADY folded into the FV tag (a minority of filers, e.g. 2022625). Subtracting it
            # would double-count -> drop cash and use the no-cash path instead of failing.
            cash = None if (g + c > ta * (1 + ASSET_TOL)) else c
        except (TypeError, ValueError):
            cash = None

    # --- closure quality -> tier ---
    if cash is not None:
        other = ta - g - float(cash)
        r.implied_other = round(other, 2)
        frac_other = other / ta
        if other < -ASSET_TOL * ta:
            r.reasons.append(f"implied other-assets {other:.0f} is negative -- grand_total too high")
            return r
        if abs(other) <= CLOSE_TOL * ta:
            r.tier = HIGH
            r.reasons.append(f"closes: total_assets {ta:.0f} = grand_total {g:.0f} + cash {float(cash):.0f} "
                             f"+ other {other:.0f} (other within {CLOSE_TOL*100:.0f}% of assets)")
            return r
        # A LARGE non-cash remainder means this grand_total is too small -- a schedule is missing
        # (the subtotal case). Reject; do not accept a subtotal just because cash is known.
        if frac_other > VERIFY_OTHER_CEILING:
            r.reasons.append(f"non-cash remainder {frac_other*100:.0f}% of assets exceeds "
                             f"{VERIFY_OTHER_CEILING*100:.0f}% (cash {float(cash):.0f}) -- grand_total "
                             f"looks like a subtotal, not accepted")
            return r
        r.tier = MEDIUM
        r.reasons.append(f"plausible but loose: implied other-assets {other:.0f} is "
                         f"{frac_other*100:.0f}% of assets (cash {float(cash):.0f})")
        return r

    # No cash figure: tier on invested fraction alone.
    if r.invested_frac >= 0.9:
        r.tier = HIGH
        r.reasons.append(f"invested fraction {r.invested_frac*100:.0f}% leaves <10% for cash+other -- tight")
    elif r.invested_frac >= invested_floor:
        r.tier = MEDIUM
        r.reasons.append(f"invested fraction {r.invested_frac*100:.0f}% is plausible but uncorroborated (no cash figure)")
    else:
        r.reasons.append(f"invested fraction {r.invested_frac*100:.0f}% is below {invested_floor*100:.0f}% -- "
                         f"this 'grand total' still looks like a subtotal; not accepted")
    return r


OTHER_FLOOR = 0.08        # non-investment, non-cash assets shouldn't exceed ~this much of total assets


def incomplete_anchor_screen(companyfacts_fv, total_assets, cash=None, *,
                             invested_floor: float = INVESTED_FLOOR, other_floor: float = OTHER_FLOOR):
    """Cheap deterministic pre-screen (no agent): flag a companyfacts FV that is likely an INCOMPLETE
    subtotal -- a near-free trigger for the anchor-adjudicator. Returns (flagged, reason).

    CASH-AWARE (sharper) when ``cash`` is given: a BDC's non-investment assets are mostly cash, so the
    remainder AFTER cash (receivables/other) should be small. A large NON-CASH remainder means an
    investment schedule is likely excluded from the tag (the 1792509 case: 87% invested but the 13%
    is $47M cash + $12M other -> NOT incomplete). Without cash, falls back to the raw invested
    fraction (coarser; a cash-heavy quarter can read as borderline)."""
    try:
        fv = float(companyfacts_fv); ta = float(total_assets)
    except (TypeError, ValueError):
        return False, "missing companyfacts_fv or total_assets"
    if not (fv > 0 and ta > 0):
        return False, "non-positive companyfacts_fv or total_assets"
    c = None
    try:
        c = float(cash) if cash is not None else None
    except (TypeError, ValueError):
        c = None
    # Use the cash-aware path only when cash is NOT already folded into the FV tag. If fv + cash
    # exceeds total_assets, the tag already includes cash (e.g. 2022625) -> fall back to the raw
    # invested fraction below rather than double-subtracting cash.
    if c is not None and c >= 0 and (fv + c) <= ta * (1 + ASSET_TOL):
        other = ta - fv - c
        frac_other = other / ta
        if frac_other > other_floor:
            return True, (f"non-cash remainder is {frac_other*100:.0f}% of total_assets (cash {c:.0f}); "
                          f"the FV tag may exclude a schedule -- run the anchor-adjudicator")
        return False, (f"closes with cash: non-cash remainder {frac_other*100:.0f}% "
                       f"(<= {other_floor*100:.0f}%); plausibly complete")
    frac = fv / ta
    if frac < invested_floor:
        return True, (f"companyfacts_fv is {frac*100:.0f}% of total_assets (< {invested_floor*100:.0f}%); "
                      f"the FV tag may be an incomplete subtotal -- run the anchor-adjudicator")
    return False, f"companyfacts_fv is {frac*100:.0f}% of total_assets (>= {invested_floor*100:.0f}%); plausibly complete"
