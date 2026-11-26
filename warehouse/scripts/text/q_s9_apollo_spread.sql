-- Slice R phase 2 fix round 1, item 7: one fund's spread differences in "S+#, #% Floor" with their tags. Read-only.
select report_date, unit_key, cell_text, value, tag_value from int_text_check_number_tag
where verdict = 'differs' and shape = 'S+#, #% Floor'
