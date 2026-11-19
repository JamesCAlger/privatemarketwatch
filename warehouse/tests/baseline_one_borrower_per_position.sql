-- Baseline: a position should belong to one borrower across its observations.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['one_borrower_per_position']) }}
select position_id, count(distinct entity_id) as borrowers
from {{ ref('fact_observation') }}
group by 1
having count(distinct entity_id) > 1
