-- A fair value or cost a correction supplies at step filed (a printed, untagged value) is stored with the number the
-- correction states: no conversion rule changes its sign or size (owner decision 2026-11-25, item c: the printed-sign
-- rule bracketed_unsigned does not act on a value that has no tag; macro field_rule, sign_unplaced). Fails on any
-- applied correction whose stored value differs from its number by the dollar tolerance or more.
select a.correction_id, a.accession, a.context_id, a.field_row, s.value_number, a.number_after
from {{ ref('int_correction_application') }} a
join {{ ref('int_correction_screen') }} s
    on s.correction_id = a.correction_id and s.accession = a.accession and s.context_id = a.context_id
where a.outcome = 'applied' and a.applied_at_step = 'filed' and a.field_row in ('fair_value', 'cost')
  and a.value_column = 'value'
  and not coalesce(abs(a.number_after - s.value_number) < {{ var('cmp_amount_tolerance')['dollar'] }}, false)
