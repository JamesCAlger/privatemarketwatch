{#- Baseline (spec section 8, D1; slice 4 Task 4): rate pairs of cmp_rate with one cause, on one basis and one field.
    One test per basis, field and cause, so a rise in one cannot hide behind a fall in another and the two bases are
    never summed. The ceiling is var('cmp_rate_max')[basis][field][cause].
    Slice 4 Task 5, repair d (the pattern of baseline_cmp_amount_cause): a cause detail with its own ceiling
    (var('cmp_rate_detail_max')[basis][field], keyed 'cause|detail') is counted by a test of its own (argument detail)
    and left out of its cause's count, so a rise in one detail cannot hide behind a fall in another. -#}
{% test baseline_cmp_rate_cause(model, basis, field, cause, detail=none) %}
{%- set own_details = [] -%}
{%- for key in var('cmp_rate_detail_max', {}).get(basis, {}).get(field, {}).keys() -%}
    {%- if key.split('|')[0] == cause -%}{%- do own_details.append(key.split('|')[1]) -%}{%- endif -%}
{%- endfor -%}
{%- if detail is not none -%}
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('cmp_rate_detail_max')[basis][field][cause ~ '|' ~ detail]) }}
{%- else -%}
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('cmp_rate_max')[basis][field][cause]) }}
{%- endif %}
select basis, cik, report_date, accession, context_id, field, value_new, value_production, difference, date_new,
    date_production, text_new, text_production, outcome, cause, cause_detail
from {{ model }}
where basis = '{{ basis }}' and field = '{{ field }}' and cause = '{{ cause }}'
{%- if detail is not none %}
  and cause_detail = '{{ detail }}'
{%- elif own_details | length > 0 %}
  and coalesce(cause_detail, '') not in ('{{ own_details | join("', '") }}')
{%- endif %}
{% endtest %}
