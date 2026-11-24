-- Slice 5 Task 3: every outcome and reason of int_correction_application is one of the closed list (the five outcomes,
-- each with its own reasons; applied has none). A new pair fails the build until it is written here and given a
-- ceiling in var correction_outcome_max.
with listed as (
    select * from (values
        ('applied', ''),
        ('no_op', 'evidence_only'), ('no_op', 'procedure_not_built'), ('no_op', 'equal_to_normalised'),
        ('no_op', 'already_absent'),
        ('rejected', 'target_not_found'), ('rejected', 'bridge_ambiguous'), ('rejected', 'target_not_position'),
        ('rejected', 'conflict'), ('rejected', 'expected_value_differs'), ('rejected', 'printed_cell_not_found'),
        ('rejected', 'printed_cell_not_dash_or_zero'),
        ('failed', 'value_not_numeric'), ('failed', 'value_not_date'), ('failed', 'unit_not_known'),
        ('failed', 'no_fx_rate'), ('failed', 'conversion_unresolved'),
        ('deferred', 'field_not_held'), ('deferred', 'no_companion_column'), ('deferred', 'rate_reading_not_rerun')
    ) t(outcome, reason)
)

select a.outcome, a.reason, count(*) as targets
from {{ ref('int_correction_application') }} a
anti join listed l on l.outcome = a.outcome and l.reason = coalesce(a.reason, '')
group by 1, 2
