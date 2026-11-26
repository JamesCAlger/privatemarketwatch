-- Slice R phase 3 fix round 1 (2026-11-26): every row the fix 1a mechanism takes out of a check, listed: an all-in TAG
-- equal to the spread or the floor alone, with no printed all-in rate that agrees with the tag (the tag holds another
-- leg). Leg identity d rows (verdict not_testable), base-level rows of the proposed rate (input_state
-- all_in_tag_is_leg), and constraint 5 rows of the read model (input_state all_in_tag_is_leg). Against a ceiling set to
-- the measured count (baseline_max.int_text_all_in_tag_is_leg). Measured 2026-11-26: 18 rows (d 8, base level 5,
-- constraint 5 5), all one filer's tags (owner item 6).
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_all_in_tag_is_leg']) }}
select 'leg_d' as check_name, cik, report_date, accession, context_id, lhs as all_in, rhs as margin_plus_floor, detail
from {{ ref('int_text_check_leg_arithmetic') }}
where verdict = 'not_testable'
union all
select 'base_level', cik, report_date, accession, context_id, all_in, spread, floor::varchar
from {{ ref('int_text_check_base_level') }}
where input_state = 'all_in_tag_is_leg' and is_proposed
union all
select 'constraint_5', cik, report_date, accession, context_id, null, null, reference_rate
from {{ ref('int_text_rate_constraint') }}
where input_state = 'all_in_tag_is_leg'
