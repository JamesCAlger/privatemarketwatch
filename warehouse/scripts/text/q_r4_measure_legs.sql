-- Slice R phase 1 measurement (2026-11-26): shape legs, the best-matching tag per printed number of each parts-stating
-- shape (equal share >= 0.5, or the top one). Read-only.
with r as (
    select s.cik, u.header_signature, s.shape, s.cell_count, l.number_label, l.tag_field, l.compared, l.equal, l.equal_bps
        , round(l.equal_share, 3) as eq_share
        , row_number() over (partition by l.shape_key, l.number_label order by l.equal desc, l.equal_bps desc, l.tag_field) as rk
    from int_text_check_shape_legs l
    join int_text_shape_unit s on s.shape_key = l.shape_key
    join int_text_column_unit u on u.unit_key = s.unit_key
)
select cik, header_signature, shape, cell_count, number_label, tag_field, compared, equal, equal_bps, eq_share
from r where rk = 1 and cell_count >= 5
order by cik, header_signature, cell_count desc, shape, number_label
