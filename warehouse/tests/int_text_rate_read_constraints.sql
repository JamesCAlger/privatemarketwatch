-- Owner addition A (2026-11-26), constraints 1 to 3 on the read model, the same for every fund. Meaning is defined by
-- the relationships between fields, not by the label a rule assigned. Returns every position that breaks one:
--   A1  a spread (or PIK spread) with no reference rate and no code printed (a number with no reference rate is a
--       fixed rate). Fix round 1: a printed code that no rule resolves counts as a reference rate here.
--   A2  a floor with no reference rate.
--   A3  rate type fixed with a reference rate, a spread or a floor.
-- int_text_rate_read does not apply a reading that breaks them (status constraint_*), so this returns no row; a model
-- change that lets one through fails the build. The unit test int_text_rate_read_constraints_drop_real_errors shows a
-- real error of each kind is caught.
select accession, context_id, 'A1_spread_needs_reference_rate' as constraint_name
from {{ ref('int_text_rate_read') }}
where (spread is not null or pik_spread is not null) and reference_rate is null and not coalesce(code_printed, false)
union all
select accession, context_id, 'A2_floor_needs_reference_rate'
from {{ ref('int_text_rate_read') }}
where floor is not null and reference_rate is null and not coalesce(code_printed, false)
union all
select accession, context_id, 'A3_fixed_has_no_floating_terms'
from {{ ref('int_text_rate_read') }}
where rate_type = 'fixed' and (reference_rate is not null or coalesce(code_printed, false) or spread is not null or floor is not null
                               or pik_spread is not null)
