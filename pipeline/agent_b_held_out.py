"""Agent B3 held-out promotion gate (deterministic; the check B2 cannot game).

Given per-quarter ledger SNAPSHOTS for a CIK -- ``baseline`` (pre-correction) and
``trial`` (after applying the staged B2 correction in a trial rebuild) -- decide whether
the correction may be PROMOTED. The gate is PURE over the snapshots: producing them
(re-running the full ledger on trial holdings) is the B2 driver's job; the un-gameable
JOINT predicates live here, mirroring ``pipeline/identifier_held_out.py``.

A correction PASSES only if ALL hold:
 - the target flag(s) are cleared in the target quarter;
 - NO new flag appears in ANY quarter (trial flags subset of baseline) -- this catches
   held-out regressions AND over-broad delete-to-balance rules that fire elsewhere;
 - total FV-at-risk is non-increasing;
 - (conservation target) the residual moved toward the anchor in the target quarter AND no
   quarter over-deletes BELOW the anchor beyond tolerance (the delete-to-balance guard);
 - D01/D02 disposition bands hold within tolerance;
 - >= ``min_held_out`` non-target quarters are covered in BOTH baseline and trial (else the
   correction is overfit-by-construction -- it was only ever seen on one quarter).

Snapshot (one dict per quarter)::

    {"quarter": "2024-12-31",
     "flags": ["fv_conservation", "C113:row5"],            # flag ids firing that quarter
     "fv_at_risk": 1234567.0,
     "conservation": {"value_sum": 337225000.0, "anchor_value": 316555000.0},  # optional
     "bands": {"D01_count": 10, "D01_fv": 5.0, "D02_count": 2, "D02_fv": 1.0}}  # optional

Cache-only, read-only. ASCII-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GateResult:
    cik: str
    target_quarter: str
    verdict: str = "PASS"
    checks: dict = field(default_factory=dict)   # predicate name -> bool
    reasons: list = field(default_factory=list)

    def _fail(self, name: str, reason: str) -> None:
        self.checks[name] = False
        self.verdict = "FAIL"
        self.reasons.append(reason)

    def _pass(self, name: str) -> None:
        self.checks.setdefault(name, True)


def _flags(snap: dict | None) -> set:
    return set((snap or {}).get("flags", []) or [])


def gate_correction(
    *,
    cik: str,
    target_quarter: str,
    target_flags,
    baseline: dict,
    trial: dict,
    min_held_out: int = 2,
    fv_epsilon: float = 1.0,
    residual_tol: float = 0.0,
    band_count_tol: int = 0,
    band_fv_tol: float = 0.0,
    anchor_undershoot_tol: float = 0.0,
) -> GateResult:
    """Apply the joint promotion predicates over baseline vs trial quarter snapshots."""
    target_flags = set(target_flags) if not isinstance(target_flags, str) else {target_flags}
    res = GateResult(cik=cik, target_quarter=target_quarter)

    # --- target cleared (in the target quarter) ---
    if target_quarter not in trial:
        res._fail("target_cleared", f"target quarter {target_quarter} absent from trial snapshots")
    else:
        still = target_flags & _flags(trial[target_quarter])
        if still:
            res._fail("target_cleared", f"target flag(s) still present in {target_quarter}: {sorted(still)}")
        else:
            res._pass("target_cleared")

    # --- no NEW flag in ANY quarter (trial subset of baseline) ---
    new_anywhere = {}
    for q, snap in trial.items():
        new = _flags(snap) - _flags(baseline.get(q))
        if new:
            new_anywhere[q] = sorted(new)
    if new_anywhere:
        res._fail("no_new_flags", f"correction introduced new flag(s): {new_anywhere}")
    else:
        res._pass("no_new_flags")

    # --- total FV-at-risk non-increasing ---
    base_fv = sum(float((s or {}).get("fv_at_risk", 0) or 0) for s in baseline.values())
    trial_fv = sum(float((s or {}).get("fv_at_risk", 0) or 0) for s in trial.values())
    if trial_fv > base_fv + fv_epsilon:
        res._fail("fv_at_risk_non_increasing",
                  f"FV-at-risk rose {base_fv:.0f} -> {trial_fv:.0f}")
    else:
        res._pass("fv_at_risk_non_increasing")

    # --- conservation: residual moved toward anchor + no over-deletion below anchor ---
    def _cons(snap):
        return (snap or {}).get("conservation")

    if _cons(baseline.get(target_quarter)) and _cons(trial.get(target_quarter)):
        b = _cons(baseline[target_quarter]); t = _cons(trial[target_quarter])
        anchor = float(t.get("anchor_value", b.get("anchor_value", 0)) or 0)
        base_resid = abs(float(b.get("value_sum", 0) or 0) - anchor)
        trial_resid = abs(float(t.get("value_sum", 0) or 0) - anchor)
        # If the target was ALREADY reconciled at baseline (no target flag), there is no residual to
        # improve -- e.g. an anchor-adjudicator correction made value_sum == the corrected anchor with
        # no holdings change needed (1743415: the tag was wrong, the extraction was right). Requiring
        # strict improvement there is unsatisfiable; target_cleared + no_new_flags already cover it.
        if not (target_flags & _flags(baseline.get(target_quarter))):
            res._pass("residual_improved")
        elif trial_resid >= base_resid - residual_tol:
            res._fail("residual_improved",
                      f"conservation residual did not improve in {target_quarter}: "
                      f"{base_resid:.0f} -> {trial_resid:.0f}")
        else:
            res._pass("residual_improved")
        # Over-deletion guard across ALL quarters with conservation in both. Reject only
        # newly introduced or worsened undershoots; pre-existing undercounts are separate
        # blockers and should not invalidate an otherwise targeted rule.
        overdel = {}
        for q in trial:
            tc, bc = _cons(trial.get(q)), _cons(baseline.get(q))
            if not (tc and bc):
                continue
            a = float(tc.get("anchor_value", bc.get("anchor_value", 0)) or 0)
            trial_delta = float(tc.get("value_sum", 0) or 0) - a
            base_delta = float(bc.get("value_sum", 0) or 0) - a
            if trial_delta < -anchor_undershoot_tol and trial_delta < base_delta - anchor_undershoot_tol:
                overdel[q] = round(trial_delta, 2)
        if overdel:
            res._fail("no_over_deletion",
                      f"value_sum pushed BELOW anchor (delete-to-balance) in: {overdel}")
        else:
            res._pass("no_over_deletion")

    # --- D01/D02 disposition bands hold within tolerance ---
    band_fail = {}
    for q in trial:
        tb = (trial.get(q) or {}).get("bands"); bb = (baseline.get(q) or {}).get("bands")
        if not (tb and bb):
            continue
        for k in ("D01_count", "D02_count"):
            if abs(int(tb.get(k, 0)) - int(bb.get(k, 0))) > band_count_tol:
                band_fail.setdefault(q, []).append(f"{k} {bb.get(k)}->{tb.get(k)}")
        for k in ("D01_fv", "D02_fv"):
            if abs(float(tb.get(k, 0) or 0) - float(bb.get(k, 0) or 0)) > band_fv_tol:
                band_fail.setdefault(q, []).append(f"{k} {bb.get(k)}->{tb.get(k)}")
    if band_fail:
        res._fail("bands_hold", f"disposition bands moved beyond tolerance: {band_fail}")
    else:
        res._pass("bands_hold")

    # --- held-out coverage: >= min_held_out non-target quarters in BOTH ---
    held_out = [q for q in trial if q != target_quarter and q in baseline]
    if len(held_out) < min_held_out:
        res._fail("held_out_coverage",
                  f"only {len(held_out)} held-out quarter(s) covered, need >= {min_held_out} "
                  f"(overfit-by-construction risk)")
    else:
        res._pass("held_out_coverage")

    if res.verdict == "PASS":
        res.reasons.append(
            f"all predicates clear; target cleared in {target_quarter}, "
            f"{len(held_out)} held-out quarter(s) not regressed")
    return res


def print_gate(res: GateResult, log=print) -> None:  # pragma: no cover
    log(f"=== B3 held-out gate -- CIK {res.cik} target {res.target_quarter} ===")
    for name, ok in res.checks.items():
        log(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    log(f"VERDICT: {res.verdict}")
    for r in res.reasons:
        log(f"  - {r}")
