-- Slice 5 Task 3: every applied correction names a field row int_field_corrected holds, and that row shows the change:
-- status corrected or withdrawn, and the column the correction sets (value, currency or fx_rate) holds the value after
-- the correction (value_after; null for a withdrawal) and differs from before. A correction applied beside a duplicate
-- of the same value (the duplicate wins the pick) passes on the value, whichever correction_id the row names.
-- Slice 5 Task 4: a maturity date sets value_date (date_after); a kind sets rate_kind (kind_after) and must change it;
-- a correction of a rate reading input (step reading_input) shows the reading after it (number_after is the field
-- row's value after the reading ran again, not the corrected input).
select a.correction_id, a.accession, a.context_id, a.field_row, a.value_column, a.value_after, f.status, f.value,
    f.currency, f.fx_rate
from {{ ref('int_correction_application') }} a
left join {{ ref('int_field_corrected') }} f
    on f.accession = a.accession and f.context_id = a.context_id and f.field = a.field_row
where a.outcome = 'applied'
  and (
    f.field is null
    or f.status not in ('corrected', 'withdrawn')
    or (a.value_column = 'value' and a.field_row <> 'maturity_date' and (
            f.value is distinct from a.number_after
            or (f.value is not distinct from f.value_normalised and f.status is not distinct from 'corrected')))
    or (a.value_column = 'value' and a.field_row = 'maturity_date' and (
            f.value_date is distinct from a.date_after
            or (f.value_date is not distinct from f.value_date_normalised and f.status is not distinct from 'corrected')))
    or (a.value_column = 'rate_kind' and (
            f.rate_kind is distinct from a.kind_after or f.rate_kind is not distinct from f.rate_kind_normalised))
    or (a.value_column = 'currency' and (
            f.currency is distinct from a.currency_after or f.currency is not distinct from f.currency_normalised))
    or (a.value_column = 'fx_rate' and (
            f.fx_rate is distinct from a.number_after or f.fx_rate is not distinct from f.fx_rate_normalised))
  )
