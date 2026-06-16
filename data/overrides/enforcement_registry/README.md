# Enforcement Registry

Governance layer over the global rules' OWN blocking flags. It does NOT decide
blocking -- it governs which already-blocking-eligible rules actually gate. Authority
comes from upstream (`promoted` / `BLOCK_VERIFIED` / `blocks_verified` /
`confirmed_impossible`); a rule not self-declared blocking-eligible has no path to
`blocking`.

Read by the publication/quality-tier gate (sets tier; does NOT fail the build) and the
enforcement-preview dry-run (`scripts/enforcement_preview.py`).

## What is actually LIVE (small -- read `governance_policy.md`)

Only three governance rules are active today: (1) the publication rule, (2) the
FP-clear guard, (3) the disposition audit. Everything else is dormant scaffolding for
a gold-set future that is not yet built. The on-disk files are split to reflect that
honestly rather than look more built-out than they are.

### Live files

- `enforcement_registry.csv` -- the day-one BLOCKING floor ONLY (5 rules), lean active
  columns. This is the entire active gate:
  - R07 / E02   : confirmed_impossible (FV > total assets). Row quarantine.
  - SRC_BDC01   : block_verified under-inclusion (kept WIDE -- the false-negative
    direction; dry-run shows 0 currently-verified quarters flip, so wide is free).
  - GAV_BDC01   : block_verified GAV blocker.
  - C201        : block_verified issuer_name missing.
- `governance_policy.md` -- the 3 live governance rules in full.
- `blocker_disposition_ledger.csv` -- append-only per-blocker disposition audit
  (the B agent writes here; current disposition = latest row per blocker key).
- `enforcement_change_log.csv` -- append-only RULE-governance log (advisory->blocking).

### Dormant files (do NOT action until a gold set exists)

- `enforcement_registry_dormant.csv` -- candidate rules; none can promote
  (`gold_* = null`, `promotion_gate` unsatisfiable). Previewable as what-if only.
- `anchor_precedence.csv` -- precedence ladder; barely bites (v1 BDC is single-anchor
  almost everywhere; no cross-target FV anchor exists -- measured CUSIP overlap = 0).

## Materiality (dual) -- applies to the FV-bearing blockers

`block <=> (pct >= tol_pct AND affected_fv >= deminimis_floor_usd) OR (affected_fv >= hard_trigger_usd)`

Day-one: tol 0.05, floor $2M, hard trigger $20M. NOTE: the ledger does not yet carry
per-flag affected_FV for row_validation/gav, so dual materiality degrades to
`presence_only` for those (see the dry-run's `materiality_mode`). Adding affected_FV is
a tracked follow-up; harmless today because the floor flips 0 verified quarters.

## Auto-merge asymmetry (anti widen-the-filter)

- promote / tighten  : `registry_promotion` (auto, iff promotion_gate satisfied + dry-run
  blast radius recorded). DORMANT -- nothing promotes until a gold set exists.
- demote / loosen     : HUMAN ONLY.
