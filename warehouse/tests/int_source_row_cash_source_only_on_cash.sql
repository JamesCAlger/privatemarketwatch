-- Slice 3 Task 1, item a: cash_source is null on every row that is not cash (its not-null test covers cash rows).
select accession, context_id, cik, role, role_rule, cash_source
from {{ ref('int_source_row') }}
where not is_cash and cash_source is not null
