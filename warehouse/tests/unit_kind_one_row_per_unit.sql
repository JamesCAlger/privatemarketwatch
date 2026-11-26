-- Slice 5 Task 1 (seeds/unit_kind.csv): every unit text written in a parsed filing (stg_filed_unit, numerator or
-- numerator/denominator) and every unit text int_field_read gives a field matches at most one row of the seed. A text
-- matching two rows has no single kind, so the seed's row order would decide it; that is an error, not a rule. Returns
-- each such text with the patterns it matches.
with unit_text as (
    select distinct case when denominator is null then numerator else numerator || '/' || denominator end as unit
    from {{ ref('stg_filed_unit') }}
    union
    select distinct unit from {{ ref('int_field_read') }} where unit is not null
)

select u.unit, count(*) as rows_matched, string_agg(k.unit_pattern, ' | ' order by k.unit_pattern) as patterns
from unit_text u
join {{ ref('unit_kind') }} k on regexp_full_match(u.unit, k.unit_pattern)
group by u.unit
having count(*) > 1
