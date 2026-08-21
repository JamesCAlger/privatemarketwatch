# Pulled: duplicate rule (2026-08-12)

- rule_id: 1812554_exclude_2025q4_rollforward_disclosure_rows (CIK 1812554, Blue Owl Credit Income)
- Reason: duplicate of another live exclusion covering the same rollforward
  disclosure rows; keeping both would double-apply. Pulled during the
  2026-08-12 promoted-rule noop-regression sweep (see changelog 2026-08-12).
- Convention: dirs starting with "_" are skipped by pipeline/agent_promoted.py
  load_promoted_rules (the 0020260722 malformed-CIK lesson).
