-- Slice R phase 2: number-tag differences, grouped by fund, field and shape, with an example. Read-only.
select cik, field, shape, count(*) n, min(cell_text) example, min(round(tag_value,4)) tag_example
from int_text_check_number_tag where verdict='differs' group by all order by cik, n desc
