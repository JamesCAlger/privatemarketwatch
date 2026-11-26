-- Slice R round 3 (2026-11-26): the legs of the largest shapes of each fund (rows >= 1000): best tag per number. Read-only.
select s.cik, s.shape, s.positions, l.number_label, l.tag_field, l.compared, l.equal, l.equal_bps, l.tag_in_this_cell
    , l.rows_no_tags
from int_text_check_shape_legs l join int_text_shape_unit s using (shape_key)
where s.positions >= 1000 and (l.equal > 0 or l.equal_bps > 0)
qualify row_number() over (partition by l.shape_key, l.number_label order by greatest(l.equal, l.equal_bps) desc) = 1
order by s.cik, s.positions desc, l.number_label
