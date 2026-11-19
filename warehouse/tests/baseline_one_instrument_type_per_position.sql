-- Baseline: a position should keep one instrument type across its observations. Blanks are not counted.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['one_instrument_type_per_position']) }}
select position_id, count(distinct instrument_type_as_read) as values_seen
from {{ ref('fact_observation') }}
group by 1
having count(distinct instrument_type_as_read) > 1
