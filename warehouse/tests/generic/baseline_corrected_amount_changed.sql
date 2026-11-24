{#- Baseline (slice 5 Task 3, a stop condition of the brief made a rule): published amount rows whose corrected value
    differs from the normalised value, or whose status a correction moved, for one field, against a ceiling
    var('corrected_amount_changed_max')[field] set to the measured count. A correction that changes a published fair
    value, cost or principal outside the measured groups fails the build. -#}
{% test baseline_corrected_amount_changed(model, field) %}
{{ config(tags=['baseline_ceiling'], severity='error', warn_if='>0', error_if='>' ~ var('corrected_amount_changed_max')[field]) }}
select f.cik, f.report_date, f.accession, f.context_id, f.field, f.value_normalised, f.value, f.status, f.reason,
    f.correction_id, r.row_reason
from {{ model }} f
join {{ ref('int_row_corrected') }} r on r.accession = f.accession and r.context_id = f.context_id
where r.is_published and f.field = '{{ field }}'
  and (f.value is distinct from f.value_normalised or f.status in ('corrected', 'withdrawn'))
{% endtest %}
