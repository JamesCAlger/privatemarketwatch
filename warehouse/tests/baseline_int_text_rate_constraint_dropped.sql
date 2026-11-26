-- Owner addition A, constraints 1 to 3 (2026-11-26): readings int_text_rate_read did not apply because they break a
-- constraint (a spread or floor with no reference rate; a fixed rate beside floating terms), one row per position and
-- field, against a ceiling set to the measured count (baseline_max.int_text_rate_constraint_dropped). Listed by fund
-- and rule in docs/baseline_text_rates_phase3_2026-11-26.md section 5.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_rate_constraint_dropped']) }}
select cik, accession, context_id, 'spread' as field, spread_status as status, spread_detail as detail
from {{ ref('int_text_rate_read') }} where spread_status like 'constraint%'
union all
select cik, accession, context_id, 'pik_spread', pik_spread_status, null
from {{ ref('int_text_rate_read') }} where pik_spread_status like 'constraint%'
union all
select cik, accession, context_id, 'floor', floor_status, null
from {{ ref('int_text_rate_read') }} where floor_status like 'constraint%'
union all
select cik, accession, context_id, 'all_in_rate', all_in_rate_status, all_in_source
from {{ ref('int_text_rate_read') }} where all_in_rate_status like 'constraint%'
