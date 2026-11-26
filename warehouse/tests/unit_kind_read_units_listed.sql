-- Slice 5 Task 1 (seeds/unit_kind.csv): every unit text int_field_read gives a field that takes a unit kind (the five
-- amount fields and the four rate fields; not maturity_date) matches exactly one row of the seed. A unit the seed does
-- not list would silently read as other; a unit that is not an amount or rate unit is listed with kind other on
-- purpose. Returns each unit with the number of seed rows it matches (0, or more than 1) and the rows read in it.
with read_unit as (
    select unit, count(*) as rows_read
    from {{ ref('int_field_read') }}
    where field in {{ amount_rule_fields() }}
       or field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread')
    group by unit
    having unit is not null
)

select r.unit, r.rows_read, count(k.unit_pattern) as rows_matched
from read_unit r
left join {{ ref('unit_kind') }} k on regexp_full_match(r.unit, k.unit_pattern)
group by r.unit, r.rows_read
having count(k.unit_pattern) <> 1
