-- Slice R phase 2: proposed column answers beside the column tag check. Read-only.
select p.unit_key, u.cik, u.header_text, p.column_holds_fwd, p.column_holds_rev, t.position_rows, t.tagged_rows,
  t.dominant_field, round(t.dominant_share,3) ds, t.second_field, t.second_rows
from text_proposed_column p join int_text_check_column_tags t using (unit_key)
join int_text_column_unit u using (unit_key) order by u.cik, p.unit_key
