# Pulled: target gone (2026-08-12)

- rule_id: 1508655_exclude_irgse_aggregate_2025 (CIK 1508655, Sixth Street)
- Reason: the aggregate rows this exclusion targeted no longer appear in the
  rebuilt frame (fixed upstream by wrapper/staging changes) -- the rule was a
  permanent noop tripping the drift/health gate. Pulled in the 2026-08-12
  IS-NULL re-keying sweep (commit d5da0f5 era).
- Convention: dirs starting with "_" are skipped by pipeline/agent_promoted.py
  load_promoted_rules.
