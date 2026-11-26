-- Compares every number printed in a rate shape with the tagged rate legs on the same row (text slice R phase 1,
-- 2026-11-26; every shape with a number since round 3). Evidence for an agent's parse of a shape ("which printed number
-- is which leg"), not a verdict. One row per (shape_key, number_label, tag_field), zero matches kept.
--
-- Shapes: every int_text_shape_unit row whose shape holds at least one '#' ("S+#, #% Floor", "#%", "SF+#%",
-- "#% (#% PIK)", "S+# Cash plus #% PIK, #% Floor"). Until round 3 only shapes stating parts (PIK) were compared.
-- Rows: the shape's position-row texts (int_text_cell), each position on the row (int_page_position one_row) once.
-- Numbers: macro text_numbers of the text, in order. number_label: 'n1', 'n2', ... (each number up to the fourth); and
-- 'n1+n2' (the sum of the first two) only for a shape that states a cash and a PIK part (it contains 'PIK', any case,
-- and at least two '#').
-- Tags (int_field_normalised: the filed tags converted, before any row correction; status normalised, percent):
-- interest_rate (any rate_kind), interest_rate_cash, pik_rate, spread. Every number label of the shape is paired with
-- all four fields, so a pair with no tagged row shows compared 0.
-- compared: rows where both the number and the tag exist. equal: abs(number - tag) <= 0.005. equal_bps: abs(number / 100
-- - tag) <= 0.005 (a spread printed in basis points, "S+525"). equal_share = equal / compared.
-- tag_in_this_cell: of the compared rows, those where the tag's own fact is placed in the column being read on that row
-- (int_text_cell.fact_fields holds spread, interest_rate_tag, interest_rate_cash_tag or pik_rate): the filer tagged a
-- number of this very cell, still evidence of which number it tagged. equal_in_this_cell: those that are also equal
-- (as percent or as basis points).
-- shape_rows: the shape's positions; rows_no_tags: those where none of the four tags exists ("no evidence possible",
-- apart from "evidence disagrees"). Both repeat on every row of the shape.
with shape as (
    select shape_key, unit_key, shape, shape_key_text
        , regexp_matches(shape, '(?i)pik') and length(shape) - length(replace(shape, '#', '')) >= 2 as states_parts
    from {{ ref('int_text_shape_unit') }}
    where shape like '%#%'
)

, cell as (
    select s.shape_key, s.states_parts, c.accession, c.row_index, c.fact_fields, {{ text_numbers('c.text') }} as numbers
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
    select shape_key, accession, context_id, fact_fields, 'n' || i as number_label, numbers[i] as number
    from position_cell, range(1, 5) t(i)
    where i <= len(numbers)
    union all
    select shape_key, accession, context_id, fact_fields, 'n1+n2', numbers[1] + numbers[2]
    from position_cell
    where states_parts and len(numbers) >= 2
)

, tag as (
    select accession, context_id, field as tag_field, value
        , case field when 'interest_rate' then 'interest_rate_tag' when 'interest_rate_cash' then 'interest_rate_cash_tag'
                     else field end as cell_field
    from {{ ref('int_field_normalised') }}
    where field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread')
        and status = 'normalised' and value is not null
)

, pair as (
    select n.shape_key, n.number_label, t.tag_field
        , count(*) as compared
        , count(*) filter (where abs(n.number - t.value) <= 0.005) as equal
        , count(*) filter (where abs(n.number / 100 - t.value) <= 0.005) as equal_bps
        , count(*) filter (where list_contains(n.fact_fields, t.cell_field)) as tag_in_this_cell
        , count(*) filter (where list_contains(n.fact_fields, t.cell_field)
                             and (abs(n.number - t.value) <= 0.005 or abs(n.number / 100 - t.value) <= 0.005))
            as equal_in_this_cell
    from number_long n
    join tag t on t.accession = n.accession and t.context_id = n.context_id
    where n.number is not null
    group by 1, 2, 3
)

, label as (
    select distinct shape_key, number_label from number_long where number is not null
)

, shape_rows as (
    select pc.shape_key, count(*) as shape_rows
        , count(*) filter (where not exists (
            select 1 from tag t where t.accession = pc.accession and t.context_id = pc.context_id)) as rows_no_tags
    from position_cell pc
    group by 1
)

select
    l.shape_key
    , l.number_label
    , f.tag_field
    , coalesce(p.compared, 0) as compared
    , coalesce(p.equal, 0) as equal
    , coalesce(p.equal_bps, 0) as equal_bps
    , coalesce(p.equal, 0) / nullif(p.compared, 0) as equal_share
    , coalesce(p.tag_in_this_cell, 0) as tag_in_this_cell
    , coalesce(p.equal_in_this_cell, 0) as equal_in_this_cell
    , r.shape_rows
    , r.rows_no_tags
from label l
cross join (select unnest(['interest_rate', 'interest_rate_cash', 'pik_rate', 'spread']) as tag_field) f
join shape_rows r on r.shape_key = l.shape_key
left join pair p on p.shape_key = l.shape_key and p.number_label = l.number_label and p.tag_field = f.tag_field
