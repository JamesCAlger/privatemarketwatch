-- Slice R phase 2: proposed read status by fund and field. Read-only.
select cik, status, coalesce(field, '-') field, count(*) n, count(distinct accession||context_id) positions
from int_text_rate_proposed group by all order by 1,2,3
