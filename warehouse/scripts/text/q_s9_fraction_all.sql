-- Slice R phase 2 fix round 1, item 5: proposed-read numbers below 1 in spread, all-in, cash, PIK and fixed roles, by
-- shape, with and without a tag. Read-only.
select r.cik, r.unit_key, r.shape, r.field, count(*) n, min(r.cell_text) example
from int_text_rate_proposed r where r.status = 'read' and r.field in ('spread','all_in_rate','cash_rate','pik_rate','pik_spread','fixed_rate')
  and r.value > 0 and r.value < 1 group by all order by n desc
