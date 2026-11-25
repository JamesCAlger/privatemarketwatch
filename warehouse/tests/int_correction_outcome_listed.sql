-- Slice 5 Task 3: every outcome and reason of int_correction_application is one of the closed list (the five outcomes,
-- each with its own reasons; applied has none). A new pair fails the build until it is written here and given a
-- ceiling in var correction_outcome_max.
-- Slice 5 Task 4: deferred rate_reading_not_rerun is gone (every rate correction now has a real outcome); added
-- failed value_not_known (a kind other than all_in or cash), legs_do_not_add, pik_above_rate, kind_not_decidable and
-- rate_reading_unresolved (int_rate_corrected row_failure).
with listed as (
    select * from (values
        ('applied', ''),
        ('no_op', 'evidence_only'), ('no_op', 'procedure_not_built'), ('no_op', 'equal_to_normalised'),
        ('no_op', 'already_absent'),
        ('rejected', 'target_not_found'), ('rejected', 'bridge_ambiguous'), ('rejected', 'target_not_position'),
        ('rejected', 'conflict'), ('rejected', 'expected_value_differs'), ('rejected', 'printed_cell_not_found'),
        ('rejected', 'printed_cell_not_dash_or_zero'),
        ('failed', 'value_not_numeric'), ('failed', 'value_not_date'), ('failed', 'value_not_known'),
        ('failed', 'unit_not_known'), ('failed', 'no_fx_rate'), ('failed', 'conversion_unresolved'),
        ('failed', 'legs_do_not_add'), ('failed', 'pik_above_rate'), ('failed', 'kind_not_decidable'),
        ('failed', 'rate_reading_unresolved'),
        ('deferred', 'field_not_held'), ('deferred', 'no_companion_column')
    ) t(outcome, reason)
)

select a.outcome, a.reason, count(*) as targets
from {{ ref('int_correction_application') }} a
anti join listed l on l.outcome = a.outcome and l.reason = coalesce(a.reason, '')
group by 1, 2
