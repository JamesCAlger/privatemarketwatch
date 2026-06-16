# Governance policy -- the LIVE core (3 rules)

The elaborate registry machinery (anchor precedence, promotion gate, advisory->
candidate->blocking ladder) is DORMANT until a gold set exists. What is actually
active today is three rules. Everything else is forward-looking scaffolding.

## 1. Publication rule (what ships as `verified`)

A CIK-quarter publishes as `verified` IFF a strong anchor PASSED **and** it has no
unresolved blocker. An `ESCALATED` blocker (a real error the agent could not fix)
keeps the quarter at `under_review` -- it does NOT publish as verified. This is the
guard against a known-real-error quarter shipping silently as clean.

Tier ladder (from shadow_quality_tiers.py): under_review / verified / preliminary /
unverified. `preliminary` and `under_review`/`ESCALATED` ship to the frontend
LABELLED, never withheld and never relabelled verified.

## 2. FP-clear guard (what stops the agent self-certifying)

The B agent may move a blocker to `FIXED` (the deterministic gate is the checker:
residual->0 + clean baseline diff) or `ESCALATED` (conservative; stays red) on its
own. It may NOT move a blocker to `FALSE_POSITIVE` on its own argument. FP requires
either:
  - an INDEPENDENT anchor of equal-or-higher precedence on the same quantity that
    refutes it (programmatic), OR
  - a human spot-audit (for single-anchor / blind cells, which is most of v1 BDC --
    no second anchor exists, so the human is the only FP adjudicator).

This is the single non-negotiable guard: without it, "push everything to the agent"
degenerates into the agent clearing its queue to green by calling real errors FPs.
The B agent's fixed/not-fixed/FP dispositions give a running PRECISION (FP-rate)
estimate -- but the FP claims must be spot-audited, and this measures precision, NOT
recall (the agent never sees the suppressed set, so it cannot bound false negatives).

## 3. Disposition audit (trust + reversibility)

Every blocker transition is appended to `blocker_disposition_ledger.csv`
(timestamp, cik, report_date, rule_id, position_key, from_state, to_state,
authorizer, evidence, independent_anchor, fp_spot_audited). Current disposition =
latest row per blocker key. This is the audit trail and the reversibility surface.
Distinct from `enforcement_change_log.csv`, which logs RULE-governance transitions
(advisory->blocking), not per-blocker instances.

## Dormant (do not action until a gold set exists)

- `enforcement_registry_dormant.csv` -- candidate rules; none can promote
  (`gold_* = null`, `promotion_gate` unsatisfiable).
- `anchor_precedence.csv` -- the precedence ladder; barely bites (v1 BDC is
  single-anchor almost everywhere; no cross-target FV anchor exists -- measured).
- promotion thresholds `N_min` / `FP_max` -- placeholders filled by the gold set.
