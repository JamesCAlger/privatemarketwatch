-- Owner item c, 2026-11-25: the Apollo untagged cost after the sign-test change. The correction's outcome and the
-- corrected cost row. Read-only.
select 'application' as src, a.outcome, a.reason, a.value_before, a.value_after, a.applied_at_step
from int_correction_application a
where a.accession = '0000950170-24-094137' and a.context_id like 'C_f9b16d68%' and a.field_row = 'cost'
union all
select 'corrected', f.status, f.reason, cast(f.value_normalised as varchar), cast(f.value as varchar), f.correction_id
from int_field_corrected f
where f.accession = '0000950170-24-094137' and f.context_id like 'C_f9b16d68%' and f.field = 'cost'
