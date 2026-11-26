-- Slice R phase 2: base-level input states per fund and proposed rate (proposed-rate rows). Read-only.
select cik, proposed_rate, input_state, count(*) n
from int_text_check_base_level where is_proposed group by all order by 1,2,3
