{#- Baseline (spec section 7, D5): amount fields of int_field_normalised left unresolved, for one field and one reason.
    One test per pair, so a rise in one cannot hide behind a fall in another. Ceiling
    var('baseline_max')['int_field_normalised_unresolved_<field>_<reason>']. -#}
{% test baseline_normalised_unresolved(model, field, reason) %}
{{ config(severity='error', warn_if='>0',
          error_if='>' ~ var('baseline_max')['int_field_normalised_unresolved_' ~ field ~ '_' ~ reason]) }}
select accession, context_id, cik, report_date, field, reason, value_filed, rule_id
from {{ model }}
where status = 'unresolved' and field = '{{ field }}' and reason = '{{ reason }}'
{% endtest %}
