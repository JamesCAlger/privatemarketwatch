-- The staging model keeps one name per borrower with min(); this checks the source really has one.
select entity_id, count(distinct canonical_name) as names
from {{ source('pipeline', 'entity_lookup') }}
group by 1
having count(distinct canonical_name) > 1