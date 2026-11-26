-- Measures which field the filer's tags say a column holds (text slice R phase 1, 2026-11-26; spec section 11: "the
-- tags on cells under the header match the field named"). One row per column unit of int_text_column_unit: unit_key.
-- Used to accept a rule "this column holds field X" where the filer tags the column; it accepts nothing by itself.
--
-- Rows: the unit's non-empty position-row texts (int_text_cell). A row counts for a field when a fact read as that
-- field is placed in the column on that row (fact_fields).
-- tagged_rows: rows with at least one field fact; untagged_rows: rows with none (has_untagged_rows when above 0).
-- dominant_field: the field on the most rows, ties to the smaller field name; dominant_rows; dominant_share =
-- dominant_rows / tagged_rows. second_field, second_rows: the next one (a column carrying two fields, e.g. a coupon
-- column tagged with both the rate and the PIK rate). n_fields: distinct fields seen.
with cell as (
    select unit_key, fact_fields
    from {{ ref('int_text_cell') }}
    where text <> ''
)

, row_count as (
    select unit_key, count(*) as position_rows, count(*) filter (where len(fact_fields) > 0) as tagged_rows
    from cell
    group by 1
)

, field_rows as (
    select unit_key, field, count(*) as n
    from (select unit_key, unnest(fact_fields) as field from cell)
    group by 1, 2
)

, ranked as (
    select *, row_number() over (partition by unit_key order by n desc, field) as rk
        , count(*) over (partition by unit_key) as n_fields
    from field_rows
)

select
    u.unit_key
    , u.cik
    , u.header_signature
    , coalesce(r.position_rows, 0) as position_rows
    , coalesce(r.tagged_rows, 0) as tagged_rows
    , coalesce(r.position_rows - r.tagged_rows, 0) as untagged_rows
    , coalesce(r.position_rows - r.tagged_rows, 0) > 0 as has_untagged_rows
    , f1.field as dominant_field
    , f1.n as dominant_rows
    , f1.n / nullif(r.tagged_rows, 0) as dominant_share
    , f2.field as second_field
    , f2.n as second_rows
    , coalesce(f1.n_fields, 0) as n_fields
from {{ ref('int_text_column_unit') }} u
left join row_count r on r.unit_key = u.unit_key
left join ranked f1 on f1.unit_key = u.unit_key and f1.rk = 1
left join ranked f2 on f2.unit_key = u.unit_key and f2.rk = 2
