# Pulled: frame mismatch (2026-07-22)

- rule_id: add_2025q4_us_treasury_bills (CIK 1965934, Overland Advantage)
- Reason: row_add authored with EMPTY positions[] -- the build frame did not
  match the authoring frame, so the rule could never apply (the $172.9M missing
  treasury position). Needs a missing_position_add re-author with grounding
  (applier now exists in POST_STAGING_APPLIERS). See changelog 2026-08-12/13.
- Convention: dirs starting with "_" are skipped by pipeline/agent_promoted.py
  load_promoted_rules.
