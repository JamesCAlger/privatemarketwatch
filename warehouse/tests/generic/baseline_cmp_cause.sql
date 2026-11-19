{#- Baseline (spec section 8, D1): one-sided rows of cmp_row_set with one cause on one basis. One test per cause and
    basis, so a rise in one cannot hide behind a fall in another and the two bases are never summed. The ceiling is
    var('baseline_max')['cmp_<basis>_<cause>']. -#}
{% test baseline_cmp_cause(model, basis, cause) %}
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['cmp_' ~ basis ~ '_' ~ cause]) }}
select basis, side, cik, report_date, accession, context_id, role, role_rule, reason, fair_value, new_fair_value, cause, cause_detail
from {{ model }}
where basis = '{{ basis }}' and cause = '{{ cause }}'
{% endtest %}
