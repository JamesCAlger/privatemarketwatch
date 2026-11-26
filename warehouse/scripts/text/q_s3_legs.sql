-- Slice R phase 2: leg identities pass/fail per fund. Read-only.
select cik, identity, count(*) n, count(*) filter (where verdict='pass') pass, count(*) filter (where verdict='fail') fail,
  string_agg(distinct detail, ',') details
from int_text_check_leg_arithmetic group by all order by 1,2
