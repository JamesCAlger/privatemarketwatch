-- Slice R phase 1 measurement (2026-11-26): per fund, column units, rate-candidate columns (by reason), shape units,
-- worklist states by unit type, reference-rate read status on published and all positions. Read-only.
select 'units' as block, cik, 'column units' as what, count(*) as n from int_text_column_unit group by 1, 2, 3
union all select 'units', cik, 'rate candidates', count(*) from int_text_column_unit where is_rate_candidate group by 1, 2, 3
union all select 'units', cik, 'cand: rate tags', count(*) from int_text_column_unit where is_rate_candidate and has_rate_tags group by 1, 2, 3
union all select 'units', cik, 'cand: named by rule', count(*) from int_text_column_unit where read_rule_ids is not null group by 1, 2, 3
union all select 'units', cik, 'cand: rate text', count(*) from int_text_column_unit where has_rate_text group by 1, 2, 3
union all select 'units', cik, 'shape units', count(*) from int_text_shape_unit group by 1, 2, 3
union all select 'units', cik, 'max shapes in a column', max(n) from (select cik, unit_key, count(*) n from int_text_shape_unit group by 1, 2) group by 1, 2, 3
union all select 'worklist', cik, unit_type || ' ' || state, count(*) from int_text_worklist group by 1, 2, 3
union all select 'worklist rate-cand', cik, unit_type || ' ' || state, count(*) from int_text_worklist where is_rate_candidate group by 1, 2, 3
union all select 'read published', cik, status, count(*) from int_text_reference_rate_read where is_published group by 1, 2, 3
union all select 'read all', cik, status, count(*) from int_text_reference_rate_read group by 1, 2, 3
union all select 'read several columns', cik, cast(n_columns_named as varchar), count(*) from int_text_reference_rate_read group by 1, 2, 3
order by 1, 3, 2
