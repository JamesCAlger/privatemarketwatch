-- Slice R fix round 1 (2026-11-26): worklist states per fund and unit type, and every column unit a rule names, with its
-- shares and dated quarter lists. Read-only.
select 'states' as block, cik, unit_type || ' ' || state as what, count(*) as n, null as rows_in_unit, null as read
    , null as passing, null as failing, null as share_read, null as share_pass, null as failing_quarters
from int_text_worklist group by 1, 2, 3
union all
select 'column', w.cik, coalesce(u.group_header_text || ' / ', '') || u.header_text || ' [' || left(w.unit_key, 6) || '] ' || w.state
    , null, w.rows_in_unit, w.rows_read, w.rows_read_by_passing_rule, w.rows_read_failing, round(w.share_read, 3)
    , round(w.share_read_passing, 3), w.failing_quarters
from int_text_worklist w join int_text_column_unit u using (unit_key)
where w.unit_type = 'column' and w.read_rule_ids is not null
order by 1 desc, 2, 3
