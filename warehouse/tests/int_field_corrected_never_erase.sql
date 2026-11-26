-- Slice 5 Task 3 (never erase, spec D1): a corrected value names the correction that set it, and a row that names a
-- correction says it was corrected or withdrawn. Fails on a row with status corrected or withdrawn and no
-- correction_id, or a correction_id with any other status. Also fails where a field corrections did not touch has a
-- value other than its normalised value (nothing may change a value without a correction).
-- Slice 5 Task 4: one exception to the second clause: a rate leg derived again from corrected inputs that ends without
-- a value keeps the reading's status (unresolved or absent) and names the correction that moved it.
select accession, context_id, field, status, correction_id, value, value_normalised
from {{ ref('int_field_corrected') }}
where (status in ('corrected', 'withdrawn') and correction_id is null)
   or (correction_id is not null and status not in ('corrected', 'withdrawn')
       and not (field in {{ rate_output_fields() }} and status in ('unresolved', 'absent') and value is null
                and value_date is null))
   or (correction_id is null and (value is distinct from value_normalised or currency is distinct from currency_normalised
       or fx_rate is distinct from fx_rate_normalised or value_date is distinct from value_date_normalised
       or rate_kind is distinct from rate_kind_normalised))
