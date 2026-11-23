{#- Baseline (spec section 8, D1; slice 4 Task 4): rate pairs of cmp_rate with one cause, on one basis and one field.
    One test per basis, field and cause, so a rise in one cannot hide behind a fall in another and the two bases are
    never summed. The ceiling is var('cmp_rate_max')[basis][field][cause]. -#}
{% test baseline_cmp_rate_cause(model, basis, field, cause) %}
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('cmp_rate_max')[basis][field][cause]) }}
select basis, cik, report_date, accession, context_id, field, value_new, value_production, difference, date_new,
    date_production, text_new, text_production, outcome, cause, cause_detail
from {{ model }}
where basis = '{{ basis }}' and field = '{{ field }}' and cause = '{{ cause }}'
{% endtest %}
