-- Slice R phase 1 measurement (2026-11-26): rate-candidate columns per fund, signature, tag check and worklist state.
-- Read-only.
select u.cik, u.header_signature, count(*) as units, sum(u.position_cells) as cells, string_agg(distinct t.dominant_field, ',') as dominant
    , round(min(t.dominant_share), 2) as min_share, sum(t.untagged_rows) as untagged, string_agg(distinct w.state, ',') as states
    , bool_or(u.has_rate_tags) as tags, bool_or(u.read_rule_ids is not null) as rule, bool_or(u.has_rate_text) as txt
from int_text_column_unit u
join int_text_check_column_tags t using (unit_key)
join int_text_worklist w on w.work_key = u.unit_key
where u.is_rate_candidate
group by 1, 2 order by 1, 2
