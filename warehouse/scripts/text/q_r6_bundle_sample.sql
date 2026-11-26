-- Slice R phase 1 (2026-11-26): one bundle, the column of the largest Blue Owl two-line header. Read-only.
select b.bundle_json from int_text_bundle b join int_text_column_unit u using (unit_key)
where u.header_signature = 'interest/cash' order by u.position_cells desc limit 1
