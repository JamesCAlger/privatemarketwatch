-- The lookup has one row per name variant; a borrower has one canonical name.
select
    entity_id,
    min(canonical_name)                 as canonical_name,
    count(distinct issuer_name_variant) as alias_count
from {{ source('pipeline', 'entity_lookup') }}
group by 1
