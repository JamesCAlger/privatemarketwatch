-- Slice R phase 2 fix round 1, item 5: read numbers below 1 whose tag is 100 times larger (a rate printed as a
-- fraction), by fund, unit, shape and field, with examples. Read-only.
select cik, unit_key, shape, field, count(*) n, min(cell_text) example, min(tag_value) tag_example
from int_text_check_number_tag
where value < 1 and value > 0 and tag_value is not null and abs(tag_value - value * 100) <= 0.005
group by all order by n desc
