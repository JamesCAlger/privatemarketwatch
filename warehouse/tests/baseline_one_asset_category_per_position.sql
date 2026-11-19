-- Baseline: a position should keep one asset category across its observations.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['one_asset_category_per_position']) }}
select position_id, count(distinct asset_category_as_read) as values_seen
from {{ ref('fact_observation') }}
group by 1
having count(distinct asset_category_as_read) > 1
