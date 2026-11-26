-- Slice R fix round 2 (2026-11-26): worklist states per fund and unit type, and every column unit a rule names with its
-- read statuses (positions). Read-only.
select 'states' as block, cik, unit_type || ' ' || state as what, count(*) as n, null as in_unit, null as read
    , null as checked, null as unchecked, null as failed, null as unspecified, null as failing_quarters
from int_text_worklist group by 1, 2, 3
union all
select 'column', w.cik, coalesce(u.group_header_text || ' / ', '') || u.header_text || ' [' || left(w.unit_key, 6) || '] ' || w.state
    , null, w.rows_in_unit, w.rows_read, w.rows_read_checked, w.rows_read_unchecked, w.rows_read_failed
    , w.rows_read_unspecified, w.failing_quarters
from int_text_worklist w join int_text_column_unit u using (unit_key)
where w.unit_type = 'column' and w.read_rule_ids is not null
order by 1 desc, 2, 3
