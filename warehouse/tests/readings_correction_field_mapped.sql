-- Slice 5 Task 2: every loaded correction field has exactly one row in seed correction_field whose store_pattern (RE2,
-- whole store name) matches the correction's store. A new field, or a field in a new store, fails the build until the
-- seed says at which step it acts.
select c.store, c.field, count(f.correction_field) as seed_rows, count(*) as corrections
from {{ ref('stg_correction') }} c
left join {{ ref('correction_field') }} f
    on f.correction_field = c.field and regexp_full_match(c.store, f.store_pattern)
group by c.store, c.field, c.correction_id
having count(f.correction_field) <> 1
