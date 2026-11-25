-- Slice 5 Task 4 (carried from the Task 3 review): the cost of the 44 contexts made positions by a zero fair value
-- (row reason correction_supplies_fair_value), filed and corrected, to correct baseline section 2.4. Read-only.
select r.row_reason, count(*) as contexts, sum(c.value) as cost_corrected, sum(c.value_normalised) as cost_before
from int_row_corrected r
left join int_field_corrected c on c.accession = r.accession and c.context_id = r.context_id and c.field = 'cost'
where r.row_reason <> 'filed'
group by all order by 1
