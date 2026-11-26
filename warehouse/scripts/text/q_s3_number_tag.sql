-- Slice R phase 2: number-tag agreement per fund and field. Read-only.
select cik, field, count(*) n, count(*) filter (where verdict='equal') equal, count(*) filter (where verdict='differs') differs,
  count(*) filter (where verdict='no_tag') no_tag
from int_text_check_number_tag group by all order by 1,2
