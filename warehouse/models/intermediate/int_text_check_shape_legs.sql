-- Compares the numbers printed in rate shapes that state parts with the tagged rate legs on the same row (text slice R
-- phase 1, 2026-11-26). Evidence for an agent's parse of a shape ("which printed number is which leg"), not a verdict.
-- One row per (shape_key, number_label, tag_field).
--
-- Shapes: int_text_shape_unit rows whose shape contains 'PIK' (any case) and at least two '#' ("#% (#% PIK)",
-- "#% Cash plus #% PIK", "S+# Cash plus #% PIK, #% Floor", "#% (incl. #% PIK)").
-- Rows: the shape's position-row texts (int_text_cell), each position on the row (int_page_position one_row) once.
-- Numbers: macro text_numbers of the text, in order. number_label: 'n1', 'n2', ... (each number up to the fourth), and
-- 'n1+n2' (the sum of the first two).
-- Tags (int_field_normalised: the filed tags converted, before any row correction; status normalised, percent): interest_rate (any rate_kind), interest_rate_cash,
-- pik_rate, spread.
-- compared: rows where both the number and the tag exist. equal: abs(number - tag) <= 0.005. equal_bps: abs(number / 100
-- - tag) <= 0.005 (a spread printed in basis points, "S+525"). equal_share = equal / compared.
with shape as (
    select shape_key, unit_key, shape, shape_key_text
    from {{ ref('int_text_shape_unit') }}
    where regexp_matches(shape, '(?i)pik') and length(shape) - length(replace(shape, '#', '')) >= 2
)

, cell as (
    select s.shape_key, c.accession, c.row_index, {{ text_numbers('c.text') }} as numbers
    from {{ ref('int_text_cell') }} c
    join shape s on s.unit_key = c.unit_key and s.shape_key_text = c.shape_key_text
    where c.text <> ''
)

, position_cell as (
    select c.*, p.context_id
    from cell c
    join {{ ref('int_page_position') }} p
        on p.accession = c.accession and p.row_index = c.row_index and p.placement_status = 'one_row'
)

, number_long as (
    select shape_key, accession, context_id, 'n' || i as number_label, numbers[i] as number
    from position_cell, range(1, 5) t(i)
    where i <= len(numbers)
    union all
    select shape_key, accession, context_id, 'n1+n2', numbers[1] + numbers[2]
    from position_cell
    where len(numbers) >= 2
)

, tag as (
    select accession, context_id, field as tag_field, value
    from {{ ref('int_field_normalised') }}
    where field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread')
        and status = 'normalised' and value is not null
)

select
    n.shape_key
    , n.number_label
    , t.tag_field
    , count(*) as compared
    , count(*) filter (where abs(n.number - t.value) <= 0.005) as equal
    , count(*) filter (where abs(n.number / 100 - t.value) <= 0.005) as equal_bps
    , count(*) filter (where abs(n.number - t.value) <= 0.005) / count(*) as equal_share
from number_long n
join tag t on t.accession = n.accession and t.context_id = n.context_id
where n.number is not null
group by 1, 2, 3
