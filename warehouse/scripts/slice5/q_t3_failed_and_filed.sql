-- Slice 5 Task 3: the corrections at step filed (wrapper untagged values) that are not zero fair values, and every
-- failed outcome: the value before and after and the re-run of the conversion.
select a.cik, a.correction_id, a.store, a.field, a.outcome, a.reason, a.value_before, a.value_after, a.target_role
    , fc.status as filed_status, fc.reason as filed_reason, fc.action, fc.rule_id, fc.read_unit, fc.value
    , c.value as correction_value, c.value_unit
from main.int_correction_application a
join main.stg_correction c on c.correction_id = a.correction_id
left join main.int_field_reread fc on fc.run = 'filed_corrected' and fc.accession = a.accession
    and fc.context_id = a.context_id and fc.field = a.field_row
where (a.step = 'filed' and not (a.field_row = 'fair_value' and a.value_after = '0.0')) or a.outcome = 'failed'
order by 1, 3
