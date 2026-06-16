# Enforcement Registry (day-one v1)

Governance layer over the global rules' OWN blocking flags. It does NOT decide
blocking -- it governs which already-blocking-eligible rules actually gate, at what
materiality, with what precision evidence, from which accession. Authority comes from
upstream (`promoted` / `BLOCK_VERIFIED` / `blocks_verified` / `confirmed_impossible`);
if a rule is not self-declared blocking-eligible upstream, it has no path to `blocking`.

Read by: the publication/quality-tier gate (sets tier; does NOT fail the build) and the
enforcement-preview dry-run (`scripts/enforcement_preview.py`).

## Files

- `anchor_precedence.csv` -- per quantity_group, the ranked anchors (rank 0 = gold/human).
  Drives the FALSE_POSITIVE precedence resolver and the coverage map. `independence_kind`
  distinguishes `cross_target` (different target, strong) from `same_target` (same target,
  extraction-only). For v1 BDC, FV_SUM has NO strong cross_target anchor (measured: CUSIP
  overlap with N-PORT is zero; issuer cross-source is coupled to paused entity resolution).
- `enforcement_registry.csv` -- one row per enforceable rule (the promotion queue), NOT all
  ~450 checks. `enforcement_state` ladder: advisory -> candidate -> blocking.
- `enforcement_change_log.csv` -- append-only governance log (rule state transitions).
  Distinct from the per-(cik,period,rule) blocker-disposition ledger.

## Day-one population

Blocking (the deterministic floor -- ships WITHOUT a gold set):
- R07 / E02   : confirmed_impossible (FV > total assets). Row quarantine.
- SRC_BDC01   : block_verified under-inclusion (source row missing from output).
- GAV_BDC01   : block_verified GAV reconciliation blocker.
- C201        : block_verified issuer_name missing.

Everything else: `candidate`, `gold_* = null` -> stays advisory until a source-labelled
gold set measures per-rule precision and satisfies `promotion_gate`.

## Materiality (dual)

`block <=> (pct >= tol_pct AND affected_fv >= deminimis_floor_usd) OR (affected_fv >= hard_trigger_usd)`

Day-one: tol_pct 0.05, deminimis_floor_usd 2,000,000, hard_trigger_usd 20,000,000.
NOTE: dual materiality needs affected_FV per flag in the ledger; some rules (row_validation,
gav_recon) do not yet carry it -- see the dry-run's `materiality_mode=presence_only` finding.

## Auto-merge asymmetry (anti widen-the-filter)

- promote advisory->blocking, tighten tolerance  : `registry_promotion` (auto, iff promotion_gate
  satisfied + dry-run blast radius recorded).
- demote blocking->advisory, loosen tolerance/floor : HUMAN ONLY.

## Promotion thresholds

`N_min` / `FP_max` are placeholders filled by the gold-set work; until then no candidate
can satisfy `promotion_gate`, so the blocking set stays at the deterministic floor.
