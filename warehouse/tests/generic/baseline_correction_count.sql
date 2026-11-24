{#- Baseline (slice 5 Task 3): the rows of a correction model that match one key, against a ceiling. One test per key,
    so a rise in one count cannot hide behind a fall in another. column is the model's column (or a SQL expression)
    whose value is compared with key; the ceiling is var(ceiling_var)[key]. Used for int_correction_application
    (outcome|reason), int_row_corrected (row_reason) and int_correction_target (key resolution, several targets). -#}
{% test baseline_correction_count(model, column, key, ceiling_var) %}
{{ config(tags=['baseline_ceiling'], severity='error', warn_if='>0', error_if='>' ~ var(ceiling_var)[key]) }}
select *
from {{ model }}
where {{ column }} = '{{ key }}'
{% endtest %}
