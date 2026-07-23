"""Convention verify: the deterministic checks the adjudicator cannot game.

Analogue of the anchor's balance-sheet closure check. The worker decided the
filer's rate convention from the FILING ALONE (the prompt is blind to the
classifier's numeric signals); this module joins its verdict against data the
worker never saw:

  1. CITATION RECONCILIATION -- every cited position's printed rates must map
     onto the STORED extracted rates under the claimed convention:
       all_in  : stored interest ~= printed_total   (and stored pik ~= printed_pik)
       cash_leg: stored interest ~= printed_cash, or printed_total - printed_pik
     Spread-anchored path (floating-rate rows): when the printed cash-column
     equals stored basis_spread and printed PIK equals stored pik EXACTLY, the
     stored all-in level may sit within BASE_DRIFT_TOL of the printed total
     (base-rate observation drift) -- provided the printed PIK magnitude still
     separates the two conventions. Issuer lookup normalizes away printed
     footnote markers ("(c)") before containment matching.
     A citation that reconciles under the OPPOSITE convention is a hard fail.
     >= 2 cited positions must reconcile under the claimed convention.
  2. SIGNAL-CONTRADICTION GATE -- a cash_leg verdict on a filer with the
     statistical-ceiling signature, or an all_in verdict on a filer with
     S1-convicting ordering violations, is refused (flag for human review;
     both sides documented). Thresholds are imported from the classifier so
     the gate and the classifier can never drift apart.
     S0 extension: a cash_leg verdict against an S0 arithmetic all-in proof
     (bare == cash + PIK across triple-tagged contexts), or an all_in verdict
     against label-guarded S0 cash-concept dominance, is likewise refused.
     The worker never sees S0 (prompt stays blind), so this is non-circular.
  3. TIER CAPPING -- no header/footnote citation, an applies_from claim
     earlier than the sampled filing, an S0 mixed_tag_semantics filer (single
     per-CIK verdict is ill-posed; migration needs per-row concept
     provenance), or a medium-confidence S0 disagreement, caps at MEDIUM.

Pure, dependency-light (no IO): the driver assembles stored rates and the
classifier stats and passes them in. ASCII-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.anchor_validation import HIGH, MEDIUM
from pipeline.rate_convention import (
    MIN_DUAL_ROWS,
    S1_VIOLATION_RATE,
    S1_VIOLATION_COUNT,
    CEILING_MIN_DUAL,
    CEILING_MIN_NEARCAP,
)

RATE_TOL = 0.05          # pp tolerance printed-vs-stored (rounding in either)
MIN_RECONCILED = 2
# Max plausible reference-rate drift (pp) between the stored (tagged) all-in
# level and the printed schedule's computation of the same row -- the two are
# often computed at different base-rate observation dates (conv_full: stored
# interest_rate sat ~0.3pp under printed totals while basis_spread matched
# EXACTLY). Used only by the spread-anchored path, which additionally requires
# the OPPOSITE convention's residual to exceed it, so the printed PIK magnitude
# is the separator and tiny-PIK rows can never decide through this path.
BASE_DRIFT_TOL = 0.75


@dataclass
class ConventionCheck:
    ok: bool = False
    tier: str = MEDIUM
    n_reconciled: int = 0
    n_pik_only: int = 0      # stored interest_rate NULL; pik magnitude corroborated
    n_opposite: int = 0
    n_unmatched: int = 0
    reasons: list = field(default_factory=list)


def _close(a, b) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= RATE_TOL


def _triple(p) -> tuple:
    """Stored-rate tuple compat: (ir, pik) -> (ir, pik, None); passthrough for 3."""
    t = tuple(p)
    return t if len(t) == 3 else (t[0], t[1], None)


def _fits_spread(convention: str, pt, pp, pc, stored_ir, stored_pik, stored_spread) -> bool:
    """Spread-anchored reconciliation for floating-rate rows.

    The contractual terms (spread, PIK) are time-invariant; the all-in level
    floats with the base rate and drifts between the tagging date and the
    printed schedule's computation. Requires ALL of: printed cash-column ==
    stored basis_spread (RATE_TOL), printed PIK == stored pik (RATE_TOL), and
    a printed_total whose distance from stored interest_rate under the CLAIMED
    convention is within BASE_DRIFT_TOL while the OPPOSITE convention's is
    not. The two residuals differ by exactly the printed PIK, so this path
    can only decide when the PIK magnitude cleanly separates the hypotheses.
    """
    if None in (pt, pp, pc, stored_ir, stored_spread):
        return False
    if not (_close(stored_spread, pc) and _close(stored_pik, pp)):
        return False
    r_all = abs(float(stored_ir) - float(pt))
    r_cash = abs(float(stored_ir) - (float(pt) - float(pp)))
    r_claimed, r_opposite = (r_all, r_cash) if convention == "all_in" else (r_cash, r_all)
    return r_claimed <= BASE_DRIFT_TOL < r_opposite


def _fits(convention: str, cit: dict, stored_ir, stored_pik, stored_spread=None) -> bool:
    """Does this position citation reconcile under ``convention``?"""
    pt, pp, pc = cit.get("printed_total"), cit.get("printed_pik"), cit.get("printed_cash")
    if convention == "all_in":
        if pt is not None and _close(stored_ir, pt) and (pp is None or _close(stored_pik, pp)):
            return True
        return _fits_spread(convention, pt, pp, pc, stored_ir, stored_pik, stored_spread)
    if convention == "cash_leg":
        pik_ok = pp is None or _close(stored_pik, pp)
        if pc is not None and _close(stored_ir, pc) and pik_ok:
            return True
        if pt is not None and pp is not None and _close(stored_ir, float(pt) - float(pp)) and pik_ok:
            return True
        return _fits_spread(convention, pt, pp, pc, stored_ir, stored_pik, stored_spread)
    return False


# Footnote markers only: 1-2 alphanumerics in parens ("(c)", "(h)", "(25)").
# Substantive parentheticals -- "(dba Boomi)", "(United Kingdom)" -- are
# distinguishing information and MUST survive normalization.
_FOOTNOTE_MARKER_RE = re.compile(r"\(\s*[a-z0-9]{1,2}\s*\)")


def _norm_issuer(name: str) -> str:
    """Lowercase + strip printed footnote markers and collapsed whitespace.

    Workers quote issuers as printed in the SOI, markers included ("Zendesk,
    Inc. (c)"); stored names carry extraction decoration instead. The markers
    defeat plain containment (conv_full: 8 leaves refused with rates that
    reconciled EXACTLY once matched)."""
    key = str(name or "").strip().lower()
    key = _FOOTNOTE_MARKER_RE.sub(" ", key)
    return re.sub(r"\s+", " ", key).strip(" ,;")


def _lookup(issuer: str, stored_rates: dict):
    """Fuzzy issuer match: exact, then normalized containment either way."""
    key = _norm_issuer(issuer)
    if not key:
        return None
    if key in stored_rates:
        return stored_rates[key]
    for name, rates in stored_rates.items():
        n = _norm_issuer(name)
        if key == n or key in n or n in key:
            return rates
    return None


def s1_convicts(stats: dict) -> bool:
    n_dual = int(stats.get("n_dual") or 0)
    n_viol = int(stats.get("n_viol") or 0)
    return (n_dual >= MIN_DUAL_ROWS and n_viol >= S1_VIOLATION_COUNT
            and n_viol / n_dual >= S1_VIOLATION_RATE)


def ceiling_signature(stats: dict) -> bool:
    return (int(stats.get("n_viol") or 0) == 0
            and int(stats.get("n_dual") or 0) >= CEILING_MIN_DUAL
            and int(stats.get("n_nearcap") or 0) >= CEILING_MIN_NEARCAP)


def verify_convention(leaf: dict, stored_rates: dict, stats: dict,
                      s0: dict | None = None) -> ConventionCheck:
    """Run checks 1-3 over a schema-valid leaf.

    ``stored_rates``: {issuer_name_lower: (interest_rate, pik_rate)} for the
    CIK's target quarter. ``stats``: the CIK's row from rate_convention.csv
    (n_dual, n_viol, n_nearcap). ``s0``: the CIK's S0 tag-fingerprint signal
    (rate_convention.load_s0_signal), optional. All come from data the worker
    never saw.
    """
    res = ConventionCheck()
    conv = str(leaf.get("convention") or "")

    if conv == "indeterminate":
        res.ok, res.tier = True, MEDIUM
        res.reasons.append("indeterminate verdict: no reconciliation applicable; "
                           "promotes as the conservative-default record")
        return res

    opposite = "cash_leg" if conv == "all_in" else "all_in"
    for cit in leaf.get("citations") or []:
        if cit.get("kind") != "position":
            continue
        found = _lookup(cit.get("issuer"), stored_rates)
        if found is None:
            res.n_unmatched += 1
            res.reasons.append(f"cited issuer not found in stored holdings: {cit.get('issuer')}")
            continue
        # an issuer may hold several tranches with different rates; the citation
        # reconciles if ANY tranche fits the claimed mapping
        pairs = [_triple(p) for p in (found if isinstance(found, list) else [found])]
        fits_claimed = any(_fits(conv, cit, ir, pik, sp) for ir, pik, sp in pairs)
        fits_opposite = any(_fits(opposite, cit, ir, pik, sp) for ir, pik, sp in pairs)
        ir, pik = pairs[0][0], pairs[0][1]
        if fits_claimed:
            res.n_reconciled += 1
        elif all(p[0] is None for p in pairs):
            # extraction gap (e.g. Blue Owl: PIK rows carry no interest_rate at
            # all): full mapping is unverifiable EITHER way -- corroborate the
            # PIK magnitude, count as partial, and cap the tier below
            if any(_close(p[1], cit.get("printed_pik")) for p in pairs):
                res.n_pik_only += 1
            else:
                res.reasons.append(f"'{cit.get('issuer')}': stored interest_rate null "
                                   f"and printed_pik does not match stored pik")
        elif fits_opposite:
            res.n_opposite += 1
            res.reasons.append(f"HARD FAIL: '{cit.get('issuer')}' reconciles under "
                               f"{opposite}, not {conv} (stored ir={ir}, pik={pik})")
        else:
            res.reasons.append(f"'{cit.get('issuer')}' reconciles under neither "
                               f"convention (stored ir={ir}, pik={pik}) -- parse/scale?")

    if res.n_opposite > 0:
        res.ok = False
        res.reasons.append("refused: citation(s) reconcile under the opposite convention")
        return res
    pik_only_carry = res.n_reconciled < MIN_RECONCILED <= res.n_reconciled + res.n_pik_only
    if res.n_reconciled + res.n_pik_only < MIN_RECONCILED:
        res.ok = False
        res.reasons.append(f"refused: only {res.n_reconciled} full + {res.n_pik_only} "
                           f"pik-only citation(s) reconcile (need >= {MIN_RECONCILED})")
        return res

    # signal-contradiction gate (worker never saw these numbers)
    if conv == "cash_leg" and ceiling_signature(stats):
        res.ok = False
        res.reasons.append("refused_contradiction: cash_leg verdict on a filer with the "
                           "statistical-ceiling signature -- human review")
        return res
    if conv == "all_in" and s1_convicts(stats):
        res.ok = False
        res.reasons.append("refused_contradiction: all_in verdict on a filer with "
                           "S1-convicting ordering violations -- human review")
        return res

    # S0 contradiction gate (tag-fingerprint evidence; worker never saw it)
    s0_vote = (s0 or {}).get("s0_vote")
    s0_conf = (s0 or {}).get("s0_confidence")
    if conv == "cash_leg" and s0_vote == "all_in":
        res.ok = False
        res.reasons.append("refused_contradiction: cash_leg verdict but S0 arithmetic "
                           "proof shows bare rate == cash + PIK in the filer's own "
                           "tagging -- human review")
        return res
    if conv == "all_in" and s0_vote == "cash_leg" and s0_conf == "high":
        res.ok = False
        res.reasons.append("refused_contradiction: all_in verdict but the stored rate "
                           "column is label-guarded InvestmentInterestRatePaidInCash "
                           "tagging -- human review")
        return res

    # tier
    has_header = any((c or {}).get("kind") in ("header", "footnote")
                     for c in (leaf.get("citations") or []))
    res.tier = HIGH if has_header else MEDIUM
    if not has_header:
        res.reasons.append("no header/footnote citation -- capped at MEDIUM")
    if pik_only_carry and res.tier == HIGH:
        res.tier = MEDIUM
        res.reasons.append("verdict rests on pik-only partial reconciliation (stored "
                           "interest_rate null on cited rows) -- capped at MEDIUM")
    af = leaf.get("applies_from")
    tq = str(leaf.get("target_quarter") or "")
    if af and str(af) < tq and res.tier == HIGH:
        res.tier = MEDIUM
        res.reasons.append("applies_from predates the sampled filing -- capped at MEDIUM")
    if (s0 or {}).get("s0_mixed") and res.tier == HIGH:
        res.tier = MEDIUM
        res.reasons.append("S0: stored column mixes rate-concept semantics (per-CIK "
                           "verdict is ill-posed; migration needs per-row provenance) "
                           "-- capped at MEDIUM")
    if conv == "all_in" and s0_vote == "cash_leg" and s0_conf != "high" and res.tier == HIGH:
        res.tier = MEDIUM
        res.reasons.append("S0 cash-concept dominance (unguarded labels) disagrees "
                           "-- capped at MEDIUM")
    res.ok = True
    return res
