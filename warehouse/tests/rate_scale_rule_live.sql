-- Owner ruling B (2026-11-23): every scale rule (fund rule ratio_value_is_percent) decides at least one row. A rule
-- that decides none is stale (its filing, field or print no longer fits) and fails the build, so a rule cannot
-- outlive its evidence unseen.
select r.rule_id, r.cik, r.sel_accession, r.parameter, 'scale rule decides no row' as problem
from {{ ref('stg_reading_rule') }} r
where r.action = 'ratio_value_is_percent'
  and r.rule_id not in (
      select scale_rule_id from {{ ref('int_rate_scale') }} where outcome = 'kept_as_percent' and scale_rule_id is not null
  )

